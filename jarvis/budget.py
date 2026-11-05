"""Local, process-safe reservations. Provider key limit remains the billing cap."""
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from .config import USER_DIR
from .http import ServiceError

# USD/token, verified against OpenRouter's catalog on 2026-11-05.
# Use conservative uncached prices, including tool/reasoning tokens.
PRICES={'openai/gpt-4.1-mini':(.4e-6,1.6e-6),'openai/gpt-6-sol':(2e-6,10e-6),
        'openai/gpt-6.1-terra':(1e-6,5e-6),'anthropic/claude-opus-5':(5e-6,25e-6)}


class Budget:
    def __init__(self,ident=None,limit=.10,*,path=None):
        if not math.isfinite(limit) or not .01<=limit<=5:raise ServiceError('Лимит задачи: 0.01–5 USD')
        self.ident=ident or uuid.uuid4().hex
        self.path=path or USER_DIR/'budgets.sqlite'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS budgets (id TEXT PRIMARY KEY, cap REAL, spent REAL DEFAULT 0, reserved REAL DEFAULT 0)')
            db.execute('INSERT OR IGNORE INTO budgets(id,cap) VALUES (?,?)',(self.ident,limit))

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def snapshot(self):
        with self.connect() as db:
            row=db.execute('SELECT cap,spent,reserved FROM budgets WHERE id=?',(self.ident,)).fetchone()
        return dict(zip(('limit_usd','accounted_usd','reserved_usd'),row))

    @contextmanager
    def call(self,body,model,output_tokens):
        if model not in PRICES:raise ServiceError('Для этой модели не задана цена в budget.PRICES; вызов остановлен')
        incoming,outgoing=PRICES[model]
        # UTF-8 bytes overestimates text token count; additional margin for tool wrappers.
        quote=((len(json.dumps(body,ensure_ascii=False).encode('utf-8'))+4096)*incoming+output_tokens*outgoing)*1.2
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT cap,spent,reserved FROM budgets WHERE id=?',(self.ident,)).fetchone()
            if row[1]+row[2]+quote>row[0]:raise ServiceError('Достигнут локальный лимит стоимости задачи. Новые запросы к модели остановлены.')
            db.execute('UPDATE budgets SET reserved=reserved+? WHERE id=?',(quote,self.ident))
        usage={}
        try:yield usage
        finally:
            cost=usage.get('cost')
            # An interrupted/unknown request is charged at its full reserved estimate.
            if isinstance(cost,bool) or not isinstance(cost,(int,float)) or not math.isfinite(cost) or cost<0:cost=quote
            with self.connect() as db:
                db.execute('UPDATE budgets SET spent=spent+?,reserved=MAX(0,reserved-?) WHERE id=?',(cost,quote,self.ident))
