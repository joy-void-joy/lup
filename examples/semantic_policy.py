"""Evaluate one provider-neutral fetch policy without a model call."""

from lup.policy.models import FetchUrl
from lup.policy.rules import FetchPolicy, UrlScope


def main() -> None:
    policy = FetchPolicy(
        allowed=[
            UrlScope.model_validate(
                {"origin": "https://docs.example.com", "path_prefix": "/api"}
            )
        ],
        denied=[
            UrlScope.model_validate(
                {"origin": "https://docs.example.com", "path_prefix": "/private"}
            )
        ],
    )
    allowed = policy.decide(
        FetchUrl.model_validate({"url": "https://docs.example.com/api/runtime"})
    )
    denied = policy.decide(
        FetchUrl.model_validate({"url": "https://docs.example.com/private/token"})
    )
    print(
        allowed.model_dump_json()
    )  # lup: This example should demontrate how to plug it in the query
    # lup: We'd also want a fle that does it for tool call
    print(denied.model_dump_json())


if __name__ == "__main__":
    main()
