// `tokcast predict --json` output, schema v1: a fresh install with --plan pro (synthetic,
// no history). tests/test_contract.py checks this fixture against the committed contract,
// so the mod's tests can't rely on a field tokcast doesn't write.
export const FORECAST_V1 = {
  "schema_version": 1,
  "prompt_chars": 27,
  "classification": {
    "task_type": "bugfix",
    "matched": [
      "fix",
      "crash"
    ]
  },
  "context": {
    "mode": "new chat",
    "tokens": 40000.0,
    "prompt_tokens": 6,
    "note": ""
  },
  "estimates": [
    {
      "model": "opus",
      "effort": "medium",
      "total": {
        "low": 113615,
        "median": 360054,
        "high": 1141038
      },
      "output": {
        "low": 1249,
        "median": 4501,
        "high": 16219
      },
      "level": "prior",
      "group": "bugfix (built-in assumption)",
      "n": 0,
      "adjustments": [
        "first turn x2.50 vs later turn (assumed)",
        "opus x0.90 vs sonnet (assumed)"
      ],
      "limit_pct": [
        0.09829969799999999,
        0.31151872080000004,
        0.9872260775999999
      ]
    },
    {
      "model": "opus",
      "effort": "low",
      "total": {
        "low": 68169,
        "median": 216032,
        "high": 684623
      },
      "output": {
        "low": 561,
        "median": 2025,
        "high": 7298
      },
      "level": "prior",
      "group": "bugfix (built-in assumption)",
      "n": 0,
      "adjustments": [
        "first turn x2.50 vs later turn (assumed)",
        "low effort x0.60 vs medium (assumed)",
        "opus x0.90 vs sonnet (assumed)"
      ],
      "limit_pct": [
        0.0589798188,
        0.18691088639999998,
        0.5923358195999999
      ]
    },
    {
      "model": "sonnet",
      "effort": "medium",
      "total": {
        "low": 126239,
        "median": 400060,
        "high": 1267820
      },
      "output": {
        "low": 1249,
        "median": 4501,
        "high": 16219
      },
      "level": "prior",
      "group": "bugfix (built-in assumption)",
      "n": 0,
      "adjustments": [
        "first turn x2.50 vs later turn (assumed)"
      ],
      "limit_pct": [
        0.10922198279999999,
        0.346131912,
        1.0969178640000001
      ]
    },
    {
      "model": "haiku",
      "effort": "medium",
      "total": {
        "low": 138863,
        "median": 440066,
        "high": 1394603
      },
      "output": {
        "low": 1124,
        "median": 4051,
        "high": 14597
      },
      "level": "prior",
      "group": "bugfix (built-in assumption)",
      "n": 0,
      "adjustments": [
        "first turn x2.50 vs later turn (assumed)",
        "haiku x1.10 vs sonnet (assumed)"
      ],
      "limit_pct": [
        0.1201442676,
        0.3807451032,
        1.2066105156
      ]
    }
  ],
  "history_turns": 0,
  "similar": [],
  "new_chat": null,
  "limit_window": "5h",
  "limit_readings": 0,
  "limit_now": null,
  "weekly_pct": [
    0.019496334,
    0.06178526639999999,
    0.19580212079999998
  ],
  "weekly_readings": 0,
  "limit_assumed_plan": "pro",
  "weekly_assumed_plan": "pro"
}
