import argparse
import json

from .contract import Observation
from .io import read_observations, write_observations
from .synthetic import generate
from .world_state import replay


def main():
    parser = argparse.ArgumentParser(
        description="MightyEye offline observation toolkit"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    fake = sub.add_parser("generate")
    fake.add_argument("--output", required=True)
    fake.add_argument("--frames", type=int, default=30)
    fake.add_argument("--seed", type=int, default=42)
    fake.add_argument(
        "--scenario",
        choices=["line-crossing", "zone-entry", "multi-camera"],
        default="line-crossing",
    )
    for command in ("validate", "replay"):
        sub.add_parser(command).add_argument("input")
    sub.add_parser("schema")
    demo = sub.add_parser("demo")
    demo.add_argument("--output", default="output/demo")
    demo.add_argument("--database-url")
    demo.add_argument("--no-video", action="store_true")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("input")
    ingest.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        if args.command == "demo":
            from .demo_pipeline import build_demo

            print(
                json.dumps(
                    build_demo(
                        args.output,
                        database_url=args.database_url,
                        videos=not args.no_video,
                    ),
                    indent=2,
                )
            )
        elif args.command == "serve":
            import uvicorn

            from .api import create_app

            uvicorn.run(create_app(), host=args.host, port=args.port)
        elif args.command == "ingest":
            import httpx

            with httpx.Client(base_url=args.url, timeout=30) as client:
                count = 0
                for observation in read_observations(args.input):
                    response = client.post(
                        "/observations", json=observation.model_dump(mode="json")
                    )
                    response.raise_for_status()
                    count += 1
            print(json.dumps({"submitted": count}))
        elif args.command == "generate":
            count = write_observations(
                args.output,
                generate(frames=args.frames, seed=args.seed, scenario=args.scenario),
            )
            print(
                json.dumps(
                    {
                        "synthetic": True,
                        "observation_count": count,
                        "output": args.output,
                    }
                )
            )
        elif args.command == "validate":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "observation_count": sum(
                            1 for _ in read_observations(args.input)
                        ),
                    }
                )
            )
        elif args.command == "replay":
            print(json.dumps(replay(read_observations(args.input)).summary(), indent=2))
        else:
            print(json.dumps(Observation.model_json_schema(), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
