import os
import json
from dotenv import load_dotenv
from openai import OpenAI, AuthenticationError, RateLimitError, APITimeoutError, APIConnectionError, APIStatusError
from openai.lib._parsing._responses import type_to_text_format_param


class ResponseFailure(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def settings(secrets=None):
    load_dotenv()
    secrets = secrets or {}
    return (os.getenv('OPENAI_API_KEY') or secrets.get('OPENAI_API_KEY', ''),
            os.getenv('OPENAI_MODEL') or secrets.get('OPENAI_MODEL', ''))


class ModelClient:
    def __init__(self, key, model):
        self.model = model
        self.client = OpenAI(api_key=key, timeout=120, max_retries=0)

    def generate(self, schema, system, payload):
        return schema.model_validate(self.generate_raw(schema,system,payload))

    def generate_raw(self,schema,system,payload):
        self.last_request_id=None
        self.last_exchange={'response_status':'not_received','parse_status':'not_started','api_request_id':None}
        try:
            response = self.client.responses.create(
                model=self.model, store=False,
                input=[{'role': 'system', 'content': system},
                       {'role': 'user', 'content': payload}],text={'format':type_to_text_format_param(schema)})
        except Exception as error:
            self.last_exchange.update(response_status='request_failed',parse_status='not_started',
                error_type=type(error).__name__,http_status=getattr(error,'status_code',None))
            raise
        self.last_request_id = getattr(response, '_request_id', None)
        status=getattr(response,'status',None)
        self.last_exchange.update(response_status=status,api_request_id=self.last_request_id)
        if status!='completed':
            self.last_exchange['parse_status']='not_parsed'
            reason=getattr(getattr(response,'incomplete_details',None),'reason',None)
            self.last_exchange['incomplete_reason']=reason
            raise ResponseFailure('RESPONSE_INCOMPLETE' if status=='incomplete' else 'RESPONSE_FAILED')
        if any(getattr(c,'type',None)=='refusal' for item in response.output for c in getattr(item,'content',[])):
            self.last_exchange['parse_status']='refused'
            raise ResponseFailure('MODEL_REFUSAL')
        try:
            value=json.loads(response.output_text)
        except (ValueError,TypeError):
            self.last_exchange['parse_status']='invalid_json'
            raise ResponseFailure('JSON_DECODE_ERROR') from None
        if not isinstance(value,dict):
            self.last_exchange['parse_status']='not_object'
            raise ResponseFailure('JSON_NOT_OBJECT')
        self.last_exchange['parse_status']='json_decoded'
        return value


def friendly_error(error):
    if isinstance(error, AuthenticationError):
        return 'API 认证失败，请检查密钥及项目权限。'
    if isinstance(error, RateLimitError):
        return '额度不足或请求过于频繁，请检查账户余额，稍后重试。'
    if isinstance(error, APITimeoutError):
        return '请求超时，原文已保留，请稍后重试。'
    if isinstance(error, APIConnectionError):
        return '无法连接模型服务，请检查网络后重试。'
    if isinstance(error, APIStatusError):
        return '模型服务请求失败，请检查模型名称、结构化输出支持与账户权限。'
    if isinstance(error, OSError):
        return '文件读写失败，请检查 data 目录的权限与磁盘空间。'
    return '返回格式或校验未通过；原文及已验证内容已保留，可重试。'
