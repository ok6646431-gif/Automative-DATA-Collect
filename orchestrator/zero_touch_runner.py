"""Runtime entry point that wires the version-tolerant public DART adapter into G0."""

import dart_public_resolver
import zero_touch_discovery

zero_touch_discovery.discover_dart_keys = dart_public_resolver.discover_dart_keys

if __name__ == "__main__":
    raise SystemExit(zero_touch_discovery.main())
