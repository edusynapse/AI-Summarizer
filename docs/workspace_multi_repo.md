# Multi-repo workspace (separate stores per repo)

**Hard rule:** each adjacent repo has its **own** summaries, **own** `index.sqlite` (symbols), and **own** `adjacency.sqlite`. Nothing is merged.

## Configure

```bash
# from AI-Summarizer clone
./install.sh /path/to/app
./install.sh /path/to/api

./configure_workspace.sh /path/to/app \
  --id my-app --role app \
  --sibling api=/path/to/api \
  --prefix my_app=package:my_app/

./configure_workspace.sh /path/to/api \
  --id my-api --role api \
  --sibling app=/path/to/app
```

Or edit `skills/agent_token_usage_optimization/repo/workspace.env` (gitignored).

## Build each repo separately

```bash
cd /path/to/app
python3 skills/agent_token_usage_optimization/broker.py index
# → repo/index.sqlite + repo/adjacency.sqlite for APP only
# summarize as usual…

cd /path/to/api
python3 skills/agent_token_usage_optimization/broker.py index
# → separate DBs for API only
```

## Query

```bash
cd /path/to/app
python3 skills/…/summary_broker.py workspace
python3 skills/…/summary_broker.py adjacent lib/foo.dart          # app adjacency
python3 skills/…/summary_broker.py --repo api adjacent routes/x.js  # open API's adjacency.sqlite
python3 skills/…/summary_broker.py --repo api search "settings"
```

`--repo` only **reads** the sibling skill trees listed in `WORKSPACE_SIBLINGS`.
