# Contributing

Use Python 3.11+, install `requirements.lock`, then install `.[dev]`. Work on a feature branch and open a focused pull request.

## Required checks

```sh
ruff check src tests
ruff format --check src tests
pytest -q
mightyeye-observations demo --output output/acceptance
```

CI also tests a real PostgreSQL service. Keep the original 12-field observation schema compatible; use separately versioned contracts for additional features. Never import SDK bindings outside `deepstream/`.

Add behavior tests for changed rules, confidence/unknown handling, source provenance and data migrations. Keep synthetic and real-video acceptance distinct. Update BUILD_STATUS and relevant runbooks alongside code. Real deployment acceptance requires saved evidence; an untested runtime file is not a completed hardware milestone.

Never commit camera credentials, private footage, downloaded weights, generated databases or local output. Dashboard source is plain HTML/CSS/JavaScript, formatted with Prettier. No frontend build or external CDN is needed.
