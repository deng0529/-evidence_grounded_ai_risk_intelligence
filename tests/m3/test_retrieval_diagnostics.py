"""Diagnostic transport and persisted-reason checks against actual project classes."""
from pathlib import Path
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from pydantic import SecretStr
from risk_intelligence.ingestion.companies_house.client import RetrievalError, Response
from risk_intelligence.ingestion.accounts import client as m
def response(status): return Response('/document', b'ok', status, datetime.now(UTC))

class DiagnosticsTests(unittest.TestCase):
    def client(self): return m.DocumentClient(SecretStr('SECRET_KEY'), download_hosts=('allowed.example',), pause=lambda _:None)
    def test_http_status(self):
        c=self.client(); c._request=lambda *a:(response(401), None)
        with self.assertRaises(m.DocumentRetrievalError) as ctx: c.get('/document/abc','application/pdf')
        self.assertIn('stage=CONTENT; code=HTTP_STATUS; http=401', str(ctx.exception))
    def test_redirect_codes_and_redaction(self):
        cases=[(None,'REDIRECT_LOCATION_MISSING'),('https://bad.example/a?token=SECRET_TOKEN','REDIRECT_HOST_REJECTED'),('https://allowed.example:bad/a','REDIRECT_URL_INVALID'),('https://user:SECRET_TOKEN@allowed.example/a','REDIRECT_COMPONENT_REJECTED')]
        for url,code in cases:
            with self.subTest(code=code):
                c=self.client(); c._request=lambda *a:(response(302),url)
                with self.assertRaises(m.DocumentRetrievalError) as ctx:c.get('/document/abc','application/pdf')
                self.assertEqual(ctx.exception.code,code)
                self.assertNotIn('SECRET',str(ctx.exception)); self.assertNotIn('https',str(ctx.exception))
    def test_unsigned_download(self):
        c=self.client(); calls=[]
        def request(*args):
            calls.append(args)
            return (response(302),'https://allowed.example/a?token=SECRET_TOKEN') if len(calls)==1 else (response(200),None)
        c._request=request
        self.assertEqual(c.get('/document/abc','application/pdf').status,200)
        self.assertTrue(calls[0][3]); self.assertFalse(calls[1][3])
    def test_download_stage(self):
        c=self.client(); replies=iter([(response(302),'https://allowed.example/a'),(response(403),None)])
        c._request=lambda *a:next(replies)
        with self.assertRaises(m.DocumentRetrievalError) as ctx:c.get('/document/abc','application/pdf')
        self.assertEqual(ctx.exception.stage,'DOWNLOAD'); self.assertEqual(ctx.exception.status,403)
    def test_retry_retains_reason(self):
        c=self.client(); calls=[]
        def request(*a):
            calls.append(a); raise m.DocumentRetrievalError(stage='CONTENT',code='TRANSPORT_TIMEOUT')
        c._request=request
        with self.assertRaises(m.DocumentRetrievalError) as ctx:c.get('/document/abc','application/pdf')
        self.assertEqual(len(calls),2); self.assertEqual(ctx.exception.code,'TRANSPORT_TIMEOUT')
    def test_transport_classification(self):
        for error,code in [(TimeoutError('SECRET'),'TRANSPORT_TIMEOUT'),(OSError('SECRET'),'TRANSPORT_OS_ERROR'),(m.HTTPException('SECRET'),'TRANSPORT_HTTP_ERROR')]:
            with self.subTest(code=code):
                with patch.object(m,'HTTPSConnection') as connection:
                    connection.return_value.request.side_effect=error
                    with self.assertRaises(m.DocumentRetrievalError) as ctx:self.client()._request(m.HOST,'/document/abc','application/json',True)
                    self.assertEqual(ctx.exception.code,code); self.assertNotIn('SECRET',str(ctx.exception))
                    connection.return_value.close.assert_called_once()
    def test_size_limit(self):
        with patch.object(m,'HTTPSConnection') as connection:
            reply=connection.return_value.getresponse.return_value
            reply.read.return_value=b'x'*3; reply.status=200
            c=self.client(); c.max_bytes=2
            with self.assertRaises(m.DocumentRetrievalError) as ctx:c._request(m.HOST,'/document/abc','application/pdf',True)
            self.assertEqual(ctx.exception.code,'BODY_TOO_LARGE')
    def test_service_persists_safe_reason(self):
        import ast
        tree=ast.parse((Path(__file__).resolve().parents[2]/'src/risk_intelligence/ingestion/accounts/service.py').read_text())
        handler=next(n for n in ast.walk(tree) if isinstance(n,ast.ExceptHandler) and isinstance(n.type,ast.Name) and n.type.id=='RetrievalError')
        module=ast.fix_missing_locations(ast.Module(body=handler.body,type_ignores=[]))
        for error,expected in [(m.DocumentRetrievalError(403,stage='DOWNLOAD',code='HTTP_STATUS'),'stage=DOWNLOAD; code=HTTP_STATUS; http=403'),(RetrievalError('SECRET_TOKEN'),'stage=UNKNOWN; code=UNKNOWN; http=NONE')]:
            scope={'error':error,'DocumentRetrievalError':m.DocumentRetrievalError}
            exec(compile(module,'handler','exec'),scope)
            self.assertIn(expected,scope['reason']); self.assertEqual(scope['availability'],'RETRIEVAL_FAILED')
            self.assertNotIn('SECRET',scope['reason'])

if __name__=='__main__':unittest.main()
