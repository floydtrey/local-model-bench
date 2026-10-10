import unittest
from unittest.mock import patch

from localbench.v2.ollama_driver import OllamaChatDriver, OllamaDriverError
from localbench.v2.tool_harness import ModelTurnRequest
import test_v2_ollama_driver as fixture


class TransportCaptureTests(unittest.TestCase):
    def config(self):
        return fixture._config(reasoning={'mode':'disabled','effort':None},transport='boolean')

    def request(self):
        return ModelTurnRequest(case_id='exact-case',turn=1,messages=({'role':'user','content':'authored probe'},),context_assets=(),tools=())

    def test_optional_capture_preserves_exact_response_bytes_before_parsing(self):
        raw=b'{ "message" : {"role":"assistant", "content":"exact output"}, "done":true }\n'
        captured=[]
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return raw
        driver=OllamaChatDriver(self.config(),capture_sink=lambda **item:captured.append(item))
        with patch('urllib.request.urlopen',return_value=Response()): result=driver(self.request())
        self.assertEqual(result.content,'exact output')
        self.assertEqual([i['kind'] for i in captured],['request','model_output'])
        self.assertEqual(captured[1]['data'],raw)
        self.assertEqual(captured[1]['context']['case_id'],'exact-case')
        self.assertEqual(captured[1]['context']['effective_config'],driver.effective_config.reference.to_dict())

    def test_invalid_raw_model_output_is_captured_then_native_protocol_error_remains(self):
        raw=b'incomplete JSON\x00'; captured=[]
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return raw
        with patch('urllib.request.urlopen',return_value=Response()):
            with self.assertRaises(OllamaDriverError): OllamaChatDriver(self.config(),capture_sink=lambda **item:captured.append(item))(self.request())
        self.assertEqual(captured[-1]['data'],raw)

    def test_capture_failure_does_not_silently_continue_or_issue_model_call(self):
        def fault(**item): raise RuntimeError('capture failed')
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network allowed')):
            with self.assertRaises(RuntimeError): OllamaChatDriver(self.config(),capture_sink=fault)(self.request())


if __name__=='__main__': unittest.main()
