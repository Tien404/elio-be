import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Inspect without running jobs")
    args = parser.parse_args()
    if args.check:
        print("Entrypoint ready; quiz finalizer, notifications and cleanup NOT implemented.")
        return 0
    print("NOT IMPLEMENTED: no jobs started; not working.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
