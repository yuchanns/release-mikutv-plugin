# release-mikutv-plugin

GitHub Action to package and publish [MikuTV](https://github.com/yuchanns/MikuTV) plugins (`source`, `theme`, `locale`) to GitHub Releases.

## Usage

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: yuchanns/release-mikutv-plugin@v1
```

## License

[Apache-2.0](LICENSE)
