"""Stand-ins for dbt_utils macros, used only by sqlfluff's jinja templater.

sqlfluff lints the models without running dbt, so it cannot call package
macros. Each function returns placeholder SQL of the same shape as the real
macro's output. Add a function here when a model starts using a new macro.
"""


def generate_surrogate_key(field_list: list[str]) -> str:
    """Return placeholder SQL in place of a surrogate key built from `field_list`."""
    return "md5('sqlfluff_stub')"
