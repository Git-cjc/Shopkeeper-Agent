"""
请求上下文

用于保存和传递一次请求或一次脚本执行过程中的上下文变量，
当前先维护 request_id，后续日志模块会从这里读取 request_id 并注入到每条日志中
"""

from contextvars import ContextVar

# 使用 ContextVar 而不是普通全局变量
# 是为了让并发协程之间的 request_id 互不干扰。
# ContextVar 可以翻成“上下文变量”：
# 你可以先把它理解成“每个请求各自有一份值的全局变量”。
# 这样请求 A 设置的 request_id，不会被请求 B 覆盖掉。
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="1")
