#log 日志规则

使用 log 日志时，请调用/core/logger.py 中的 setup_logger 函数:

```python
from core.logger import setup_logger
logger = setup_logger()
```

查看 log 日志时，请查看 logs/api_service.log