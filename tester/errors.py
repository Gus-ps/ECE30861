"""Instructor error envelope {message, source} for every tester endpoint."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class TesterError(Exception):
    def __init__(self, status, message, source="tester"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.source = source


def error_response(status, message, source="tester"):
    return JSONResponse(status_code=status, content={"message": message, "source": source})


def install_handlers(app: FastAPI):
    @app.exception_handler(TesterError)
    async def tester_error(_: Request, error: TesterError):
        return error_response(error.status, error.message, error.source)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, error: RequestValidationError):
        problems = "; ".join(
            f"{'.'.join(str(p) for p in problem['loc'][1:]) or 'body'}: {problem['msg']}"
            for problem in error.errors())
        return error_response(400, f"Invalid request: {problems or 'malformed body'}")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, error: StarletteHTTPException):
        return error_response(error.status_code, str(error.detail) or "Request failed")

    @app.exception_handler(Exception)
    async def unexpected(_: Request, error: Exception):
        return error_response(500, "The tester failed unexpectedly.")
