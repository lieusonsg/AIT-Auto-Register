"""Start local Turnstile Solver service"""
import sys
import os

# Compatible with running directly as a script (python services/turnstile_solver/start.py)
sys.path.insert(0, os.path.dirname(__file__))

try:
    # Prefer absolute import — allows PyInstaller to track api_solver
    from services.turnstile_solver.api_solver import create_app, parse_args
except ImportError:
    from api_solver import create_app, parse_args


def main():
    args = parse_args()
    app = create_app(
        headless=not args.no_headless,
        useragent=args.useragent,
        debug=args.debug,
        browser_type=args.browser_type,
        thread=args.thread,
        proxy_support=args.proxy,
        use_random_config=args.random,
        browser_name=args.browser,
        browser_version=args.version,
    )
    app.run(host=args.host, port=int(args.port))


if __name__ == "__main__":
    main()
