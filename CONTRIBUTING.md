# Contributing

Install `.[dev]`, run `pytest -q`, and run the checked-in fixture replay before submitting a pull request. Add tests for changes in conversion semantics and contract validation. Never import SDK bindings outside the DeepStream package. Update the schema, examples and contract documentation together when changing wire semantics. Incompatible changes require a new schema version.

Use feature branches and pull requests. Do not commit camera credentials, recordings, model weights, or local output. No real footage is required for the default test suite.
