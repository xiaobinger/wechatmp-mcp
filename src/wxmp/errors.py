# -*- coding: utf-8 -*-
"""Error types and JSON-RPC error codes."""

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class WXMPError(Exception):
    """Base class for expected, reportable failures."""

    code = INTERNAL_ERROR

    def __init__(self, message, data=None):
        super().__init__(message)
        self.message = message
        self.data = data

    def as_dict(self):
        out = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out


class ToolError(WXMPError):
    """A tool failed. Reported as an MCP tool result with isError=true."""

    code = INVALID_PARAMS


class ParamError(ToolError):
    """Invalid tool arguments."""


class LoginRequired(ToolError):
    """The browser profile has no usable WeChat console session."""

    def __init__(self, message="not logged in; run mp_account_login and scan the QR code",
                 data=None):
        super().__init__(message, data)


class BrowserUnavailable(ToolError):
    """Playwright or a usable browser binary is missing."""


class PageError(ToolError):
    """The console page did not reach the state the flow needs."""

    def __init__(self, message, data=None):
        super().__init__(message, data)


class ConfirmationRequired(ToolError):
    """A publishing or destructive action was attempted without confirm=true."""

    def __init__(self, message, data=None):
        super().__init__(message, data)