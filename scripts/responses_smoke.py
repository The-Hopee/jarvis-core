"""Two-round live function-call probe, with no external tool side effects."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import Settings,USER_DIR
from jarvis.responses_client import ResponsesClient


def main():
    settings=Settings.load();rows=[]
    tool={'type':'function','function':{'name':'submit_probe','description':'Return the requested test value',
          'parameters':{'type':'object','properties':{'value':{'type':'string'}},'required':['value'],'additionalProperties':False}}}
    for model,effort in (('openai/gpt-6-sol','high'),('openai/gpt-6.1-terra','low')):
        client=ResponsesClient(settings.api_key,model,effort=effort,max_tokens=4000)
        messages=[{'role':'user','content':'Call submit_probe with value ready. After the tool result, reply briefly with the returned value.'}]
        first=client.complete(messages,[tool])
        call=(first.get('tool_calls') or [])[0]
        if json.loads(call['function']['arguments'])!={'value':'ready'}:raise RuntimeError('unexpected arguments')
        messages.extend([first,{'role':'tool','tool_call_id':call['id'],'content':'{"value":"ready"}'}])
        final=client.complete(messages,[tool],allow_tools=False)
        rows.append({'model':model,'effort':effort,'function_call_validated':True,'final_nonempty':bool(final['content']),
                     'raw_response_items_preserved':bool(first.get('_response_items')),'usage_keys':sorted(client.last_usage)})
        print(json.dumps(rows[-1]),flush=True)
    path=USER_DIR/'benchmarks/stage08-responses-smoke.json'
    path.write_text(json.dumps(rows,indent=2),encoding='utf-8')


if __name__=='__main__':main()
