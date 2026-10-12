"""Optional progress sink; never include prompts, credentials or paper text."""


def report(callback, message):
    if callback is not None:
        try:
            callback(message)
        except Exception:
            pass  # A UI/reporting failure must not interrupt tool execution.
