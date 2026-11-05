"""Local setup/control panel. Secrets stay on the owner's Windows account."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from .config import Settings,USER_DIR,read_env
from .child_process import command
from .http import ServiceError
from .runtime import is_running,request_stop
from . import distribution

def save_settings(values):
    previous=read_env(USER_DIR/'settings.env')
    previous.update(values)
    if any('\n' in str(v) or '\r' in str(v) for v in previous.values()):raise ServiceError('В значении настройки обнаружен перенос строки')
    USER_DIR.mkdir(parents=True,exist_ok=True)
    temporary=USER_DIR/'settings.env.tmp'
    temporary.write_text(''.join(k+'='+str(v)+'\n' for k,v in sorted(previous.items())),encoding='utf-8')
    temporary.replace(USER_DIR/'settings.env')

def main(*,smoke=False):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    settings=Settings.load()
    first_run=not (USER_DIR/'settings.env').exists()
    app=tk.Tk();app.title('Jarvis — настройка и управление');app.geometry('800x730');app.minsize(720,650)
    if smoke:app.attributes('-alpha',0)
    frame=ttk.Frame(app,padding=16);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Jarvis',font=('Segoe UI',21,'bold')).grid(row=0,column=0,sticky='w')
    from . import __version__
    ttk.Label(frame,text='Версия '+__version__+' · Windows x64').grid(row=0,column=1,sticky='e')
    frame.columnconfigure(1,weight=1)
    fields={}
    entries=[('Ключ OpenRouter','OPENROUTER_API_KEY',settings.api_key),('Город','JARVIS_CITY',settings.city),
             ('Микрофон (пусто = системный)','JARVIS_MICROPHONE',str(settings.microphone or '')),
             ('Распознавание (локально)','JARVIS_ASR',settings.asr),('Озвучивание','JARVIS_TTS','windows' if first_run else settings.tts),
             ('Образец голоса WAV (необязательно)','JARVIS_VOICE_REFERENCE',settings.voice_reference),
             ('Текст речи в образце','JARVIS_VOICE_REFERENCE_TEXT',settings.voice_reference_text)]
    for row,(label,key,value) in enumerate(entries,1):
        ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=5)
        var=tk.StringVar(value=value);fields[key]=var
        if key in {'JARVIS_ASR','JARVIS_TTS'}:
            options=(('vosk','openrouter') if settings.allow_cloud_asr else ('vosk',)) if key=='JARVIS_ASR' else ('windows','openrouter','edge','off')
            widget=ttk.Combobox(frame,textvariable=var,values=options,state='readonly')
        else:widget=ttk.Entry(frame,textvariable=var,show='*' if key=='OPENROUTER_API_KEY' else '')
        widget.grid(row=row,column=1,sticky='ew',pady=5)
    row=8
    status=tk.StringVar(value='Готов к настройке.');ttk.Label(frame,textvariable=status,wraplength=740).grid(row=row,column=0,columnspan=2,sticky='w',pady=8)
    output=tk.Text(frame,height=11,wrap='word');output.grid(row=12,column=0,columnspan=2,sticky='nsew',pady=8);frame.rowconfigure(12,weight=1)

    def append(text):
        output.insert('end',str(text)+'\n');output.see('end')
    def work(title,action):
        status.set(title)
        def run():
            try:result=action()
            except Exception as exc:app.after(0,lambda msg=str(exc): (status.set('Ошибка'),append(msg)));return
            app.after(0,lambda:(status.set('Готово'),append(result or 'Готово.')))
        threading.Thread(target=run,daemon=True).start()
    def require_stop():
        if not request_stop(timeout=55):raise ServiceError('Текущая задача ещё завершается. Повторите после остановки.')
    def save(values=None):
        values=values or {k:v.get().strip() for k,v in fields.items()}
        reference=values['JARVIS_VOICE_REFERENCE']
        if reference:
            source=Path(reference).resolve()
            if not source.is_file() or source.suffix.casefold()!='.wav' or source.stat().st_size>6*1024*1024:raise ServiceError('Нужен WAV до 6 MB')
            target=USER_DIR/'voice-references/personal.wav';target.parent.mkdir(parents=True,exist_ok=True)
            if source!=target.resolve():shutil.copyfile(source,target)
            values['JARVIS_VOICE_REFERENCE']=str(target)
        # No reference is required for a reproducible base Windows voice.
        save_settings(values)
        # Cache only short base Windows clips on first setup; paid voices are explicit.
        if values['JARVIS_TTS']=='windows':
            from .progress import prepare_status_voice
            from dataclasses import replace
            prepare_status_voice(replace(settings,tts='windows'))
        return 'Настройки сохранены локально. Перезапустите помощника для применения.'
    def executable():
        state=distribution.read_state()
        return distribution.version_path(distribution.INSTALL_ROOT,state['current'])/'Jarvis.exe' if state.get('current') else Path(sys.executable)
    def run_cli(*args,timeout=90):
        argv=[str(executable()),*args] if getattr(sys,'frozen',False) else [sys.executable,'-m','jarvis',*args]
        completed=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if completed.returncode:raise ServiceError(completed.stderr[-2000:] or completed.stdout[-2000:] or 'Проверка завершилась с ошибкой')
        return completed.stdout[-5000:]
    def start():
        if is_running():return 'Джарвис уже работает.'
        save()
        if getattr(sys,'frozen',False):argv=[str(executable()),'--internal','background']
        else:argv=command('jarvis.background')
        subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        import time
        for _ in range(100):
            if is_running():return 'Джарвис работает. Скажите: «Джарвис, состояние машины».'
            time.sleep(.1)
        raise ServiceError('Запуск не подтвердился. Откройте журнал.')
    def install():
        require_stop();source=Path(sys.executable).parent
        target=distribution.install(source)
        return 'Установлено: '+str(target)+'\nЯрлыки созданы на рабочем столе и в меню Пуск.'
    def rollback():
        require_stop();return 'Выбрана версия: '+str(distribution.rollback())
    def login(kind):
        require_stop()
        argv=[str(executable()),'--'+kind+'-login'] if getattr(sys,'frozen',False) else [sys.executable,'-m','jarvis','--'+kind+'-login']
        subprocess.Popen(argv,creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
        return 'Окно подключения открыто. Введите свои данные только в этом окне.'
    def browser():
        completed=subprocess.run(command('playwright','install','chromium'),capture_output=True,timeout=600,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if completed.returncode:raise ServiceError('Браузер не установился. Проверьте интернет и повторите.')
        return 'Браузер VK установлен.'
    buttons=ttk.Frame(frame);buttons.grid(row=9,column=0,columnspan=2,sticky='ew')
    for i,(name,func) in enumerate([('Установить / обновить',install),('Сохранить настройки',save),('Запустить',start),('Остановить',lambda:(require_stop() or 'Джарвис остановлен.')),
            ('Диагностика',lambda:run_cli('--doctor')),('Проверить голос',lambda:run_cli('--speak','Я на связи, сэр.')),
            ('Микрофоны',lambda:run_cli('--list-mics')),('Выбрать образец',lambda:fields['JARVIS_VOICE_REFERENCE'].set(filedialog.askopenfilename(filetypes=[('WAV','*.wav')])))]):
        if name=='Выбрать образец':callback=func
        else:callback=lambda name=name,func=func:work(name,func)
        ttk.Button(buttons,text=name,command=callback).grid(row=i//4,column=i%4,sticky='ew',padx=3,pady=3)
    advanced=ttk.Frame(frame);advanced.grid(row=10,column=0,columnspan=2,sticky='ew')
    for i,(name,func) in enumerate([('Браузер VK',browser),('Войти в VK',lambda:login('vk')),('Войти в Telegram',lambda:login('telegram')),
                                  ('Откат версии',rollback),('Журнал',lambda:os.startfile(str(USER_DIR/'logs'))),
                                  ('Руководство',lambda:os.startfile(str(Path(sys.executable).parent/'РУКОВОДСТВО.html')))]):
        ttk.Button(advanced,text=name,command=lambda name=name,func=func:work(name,func)).grid(row=i//3,column=i%3,sticky='ew',padx=3,pady=3)
    auto=tk.BooleanVar(value=distribution.read_state().get('autostart',False))
    ttk.Checkbutton(frame,text='Запускать после входа в Windows',variable=auto,
                    command=lambda:work('Автозапуск',lambda:distribution.set_autostart(auto.get()))).grid(row=11,column=0,sticky='w')
    erase=tk.BooleanVar(value=False)
    ttk.Checkbutton(frame,text='При удалении стереть мои настройки и сессии',variable=erase).grid(row=13,column=0,columnspan=2,sticky='w')
    def uninstall():
        destructive=erase.get()
        if not messagebox.askyesno('Удалить Jarvis?','Будет удалена программа.'+(' Также будут удалены ключи, сессии и история.' if destructive else ' Ваши настройки и сессии сохранятся.')):return
        def action():
            require_stop();script=distribution.uninstall_script(erase_data=destructive)
            subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',script],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            app.after(0,app.destroy)
        work('Удаление',action)
    ttk.Button(frame,text='Удалить программу',command=uninstall).grid(row=14,column=0,sticky='w',pady=5)
    ttk.Button(frame,text='Проверить защиту данных',command=lambda:work('Локальная проверка без сети',lambda:run_cli('--privacy-check')+'\n'+run_cli('--privacy-report'))).grid(row=14,column=1,sticky='e',pady=5)
    if smoke:
        app.update()
        buttons_all=[]
        def visit(widget):
            for child in widget.winfo_children():
                if isinstance(child,ttk.Button):buttons_all.append(child)
                visit(child)
        visit(app)
        bounds=all(0<=w.winfo_rootx()-app.winfo_rootx() and w.winfo_rootx()-app.winfo_rootx()+w.winfo_width()<=app.winfo_width()
                   and w.winfo_rooty()-app.winfo_rooty()+w.winfo_height()<=app.winfo_height() for w in buttons_all)
        report={'ui_created':True,'buttons':len(buttons_all),'buttons_inside_window':bounds,'width':app.winfo_width(),'height':app.winfo_height()}
        app.destroy();print(json.dumps(report));return 0 if bounds else 1
    app.mainloop();return 0

if __name__=='__main__':raise SystemExit(main())
