# MCP Project

## Usage

Pre-requisites:

1. Google Cloud Platform OAuth 2.0 Credential
   - On Google Cloud Platform
   - Find "Gmail API" => Click "Credentials" 
   - On "OAuth 2.0 Client IDs" section => Click "Create credentials"
   - Download the credentials and store as `./creds/credentials.json`
2. Python package manager [`uv` is installed](https://docs.astral.sh/uv/)
3. Get absolute path to this project, e.g. using `pwd`

### With Claude Code CLI

> On MacOS, install with `brew install claude-code`

In the same working directory of Claude Code CLI

1. Get absolute path to this project (e.g. `pwd`)
2. Add or Edit file `.mcp.json`, with below configurations

```json
// Replace "/users/absolute/path/mcp-project" with the real path
{
  "mcpServers": {
    "mcp-gmail": {
      "command": "uv",
      "args": [
        "--directory", "/Users/absolute/path/mcp-project", "run", "-m", "src.server"
      ]
    }
  }
}
```
3. Check with `claude mcp list`

### With Claude Desktop

> On MacOS, install with `brew install claude`

1. Open Claude Desktop
2. Click on "Settings" => "Developer"
3. "Local MCP servers", click on "Edit Config"
4. Add below configurations

```json
// Replace "/Users/absolute/path/mcp-project" with the real path
{
  "mcpServers": {
    "mcp-gmail": {
      "command": "uv",
      "args": [
        "--directory", "/Users/absolute/path/mcp-project", "run", "-m", "src.server"
      ]
    }
  }
}
```

References
- https://modelcontextprotocol.io/docs/develop/connect-local-servers

## TODO

- [ ] Update OAUTH authentications to be more explicit
- [ ] Add `config.py` to manage configurations
- [ ] Add tests to test parsing functions
- [ ] ...
