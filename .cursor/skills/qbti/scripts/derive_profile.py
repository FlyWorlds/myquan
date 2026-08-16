#!/usr/bin/env python3
"""QBTI（量化行为类型指标）：把问答答案确定性地翻译为 profile.json 与 strategy_brief.json。

用法:
    python scripts/derive_profile.py --answers <answers.json> --out <dir> [--mapping <preference_mapping.yaml>]

纯标准库实现，无网络调用、无 LLM 调用。所有映射逻辑来自
references/preference_mapping.yaml，本脚本不做任何超出映射表的推断。
内置的 YAML 解析器只支持映射表实际用到的子集（缩进块映射、块/流式列表、
带引号标量、行内注释）；不支持锚点、多行标量、值内含 ASCII 冒号的未引号字符串。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# 微型 YAML 子集解析器
# ---------------------------------------------------------------------------


def _strip_comment(line: str) -> str:
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[i - 1] in " \t":
                return line[:i].rstrip()
    return line.rstrip()


def _scalar(token: str):
    token = token.strip()
    if token == "":
        return None
    if token == "{}":
        return {}
    if token == "[]":
        return []
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        return [] if not inner else [_scalar(part) for part in inner.split(",")]
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    if token == "true":
        return True
    if token == "false":
        return False
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


def _parse_block(lines: list, i: int, indent: int):
    if lines[i][1].startswith("- "):
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_map(lines: list, i: int, indent: int):
    result = {}
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent:
            break
        if ind > indent:
            raise ValueError(f"unexpected indent at line: {content!r}")
        key, sep, rest = content.partition(":")
        if not sep:
            raise ValueError(f"expected 'key:' at line: {content!r}")
        key = key.strip()
        rest = rest.strip()
        if rest:
            result[key] = _scalar(rest)
            i += 1
        elif i + 1 < len(lines) and lines[i + 1][0] > indent:
            result[key], i = _parse_block(lines, i + 1, lines[i + 1][0])
        else:
            result[key] = None
            i += 1
    return result, i


def _parse_list(lines: list, i: int, indent: int):
    result = []
    while i < len(lines):
        ind, content = lines[i]
        if ind != indent or not content.startswith("- "):
            break
        item = content[2:].strip()
        if ":" in item:
            lines[i] = (indent + 2, item)
            value, i = _parse_map(lines, i, indent + 2)
            result.append(value)
        else:
            result.append(_scalar(item))
            i += 1
    return result, i


def load_mapping(path: Path) -> dict:
    lines = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = _strip_comment(raw)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip()))
    mapping, _ = _parse_map(lines, 0, 0)
    return mapping


# ---------------------------------------------------------------------------
# 答案校验与推导
# ---------------------------------------------------------------------------

# 各维度拒答时的默认值，与 references/question_bank.md 的「默认」行保持一致
ANSWER_DEFAULTS = {
    "cluster_a_loss_reaction": "stick_to_plan",
    "cluster_b_involvement": "monthly_glance",
    "cluster_c_taste": "steady_and_boring",
    "cluster_c_volatility_stance": "neutral",
    "cluster_d_universe_style": "explorer_no_limit",
    "cluster_d_exclude_st": True,
    "cluster_e_time_capsule": "year_end",
}

ANSWER_CLUSTER_KEYS = {
    "cluster_a_loss_reaction": "cluster_a",
    "cluster_b_involvement": "cluster_b",
    "cluster_c_taste": "cluster_c",
    "cluster_d_universe_style": "cluster_d",
    "cluster_e_time_capsule": "cluster_e",
}


def resolve_answers(raw: dict, mapping: dict) -> tuple[dict, list]:
    answers = {}
    defaults_used = []
    for field, default in ANSWER_DEFAULTS.items():
        if field in raw and raw[field] is not None:
            answers[field] = raw[field]
        else:
            answers[field] = default
            defaults_used.append({
                "field": field,
                "default_value": default,
                "reason": "answer missing; question_bank default applied",
            })
    answers["cluster_c_taste_secondary"] = raw.get("cluster_c_taste_secondary")
    answers["cluster_d_preferred_sectors"] = raw.get("cluster_d_preferred_sectors") or []
    answers["cluster_d_excluded_sectors"] = raw.get("cluster_d_excluded_sectors") or []

    for field, cluster in ANSWER_CLUSTER_KEYS.items():
        if answers[field] not in mapping[cluster]:
            raise SystemExit(
                f"invalid enum for {field}: {answers[field]!r}; "
                f"allowed: {sorted(mapping[cluster])}"
            )
    secondary = answers["cluster_c_taste_secondary"]
    if secondary is not None and secondary not in mapping["cluster_c"]:
        raise SystemExit(f"invalid enum for cluster_c_taste_secondary: {secondary!r}")
    if answers["cluster_c_volatility_stance"] not in mapping["volatility_adjustments"]:
        raise SystemExit(
            f"invalid enum for cluster_c_volatility_stance: "
            f"{answers['cluster_c_volatility_stance']!r}"
        )
    sector_enum = set(mapping["sector_enum"])
    for field in ("cluster_d_preferred_sectors", "cluster_d_excluded_sectors"):
        unknown = [s for s in answers[field] if s not in sector_enum]
        if unknown:
            raise SystemExit(f"invalid sectors in {field}: {unknown}; allowed: {sorted(sector_enum)}")

    mode = mapping["cluster_d"][answers["cluster_d_universe_style"]]["sector_preference_mode"]
    if mode == "familiar_only" and not answers["cluster_d_preferred_sectors"]:
        raise SystemExit("cluster_d_universe_style=familiar_only requires cluster_d_preferred_sectors")
    if mode == "has_exclusions" and not answers["cluster_d_excluded_sectors"]:
        raise SystemExit("cluster_d_universe_style=has_exclusions requires cluster_d_excluded_sectors")
    return answers, defaults_used


def derive(answers: dict, mapping: dict) -> tuple[dict, list]:
    flags = []
    derived = {}
    derived.update(mapping["cluster_a"][answers["cluster_a_loss_reaction"]])
    derived.update(mapping["cluster_b"][answers["cluster_b_involvement"]])
    derived.update(mapping["cluster_d"][answers["cluster_d_universe_style"]])
    derived["preferred_sectors"] = answers["cluster_d_preferred_sectors"]
    derived["excluded_sectors"] = answers["cluster_d_excluded_sectors"]
    derived["exclude_st_and_risk_flags"] = bool(answers["cluster_d_exclude_st"])

    cluster_e = dict(mapping["cluster_e"][answers["cluster_e_time_capsule"]])
    horizon_flag = cluster_e.pop("flag", None)
    if horizon_flag:
        flags.append({"id": f"horizon_{answers['cluster_e_time_capsule']}", "message": horizon_flag})
    derived.update(cluster_e)

    families = list(mapping["cluster_c"][answers["cluster_c_taste"]]["factor_families"])
    secondary = answers["cluster_c_taste_secondary"]
    if secondary:
        for family in mapping["cluster_c"][secondary]["factor_families"]:
            if family not in families:
                families.append(family)
    families = families[:2]

    stance = answers["cluster_c_volatility_stance"]
    adjustment = mapping["volatility_adjustments"][stance] or {}
    if adjustment:
        primary = families[0]
        if primary in adjustment["applies_when_primary_in"]:
            injected = adjustment["inject_family"]
            if injected not in families:
                families.append(injected)
            flags.append({"id": f"volatility_adjustment_{stance}", "message": adjustment["flag"]})
    derived["factor_affinity"] = families
    derived["volatility_stance"] = stance

    for check in mapping["consistency_checks"]:
        if "when" in check:
            if _check_matches(check["when"], derived):
                flags.append({"id": check["id"], "message": check["flag"]})
        elif "assert" in check:
            rule = check["assert"]
            if derived["risk_tolerance"] in rule["if_risk_tolerance_in"]:
                limit = rule["then_max_position_pct_lte"]
                if derived["max_position_pct"] > limit:
                    raise SystemExit(
                        f"mapping table violates safety assertion {check['id']}: "
                        f"risk_tolerance={derived['risk_tolerance']} but "
                        f"max_position_pct={derived['max_position_pct']} > {limit}"
                    )
    return derived, flags


def _check_matches(conditions: dict, derived: dict) -> bool:
    for key, expected in conditions.items():
        if key.endswith("_contains"):
            field = key[: -len("_contains")]
            if expected not in derived.get(field, []):
                return False
        elif key.endswith("_in"):
            field = key[: -len("_in")]
            if derived.get(field) not in expected:
                return False
        else:
            raise ValueError(f"unsupported consistency condition: {key}")
    return True


def build_strategy_brief(derived: dict, mapping: dict, profile_name: str) -> dict:
    pools = []
    for family in derived["factor_affinity"]:
        pool = mapping["factor_family_pools"][family]["pool"]
        if pool not in pools:
            pools.append(pool)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_profile": profile_name,
        "candidate_factor_pools": pools,
        "factor_family_tags": derived["factor_affinity"],
        "universe_filters": {
            "preferred_sectors": derived["preferred_sectors"],
            "excluded_sectors": derived["excluded_sectors"],
            "exclude_st_and_risk_flags": derived["exclude_st_and_risk_flags"],
        },
        "position_constraints": {
            "max_position_pct": derived["max_position_pct"],
            "stop_loss_discipline": derived["stop_loss_discipline"],
        },
        "rebalance_frequency": derived["rebalance_frequency"],
        "target_holding_period_days": derived["target_holding_period_days"],
        "recommended_next_skills": [
            "skill-factor-evaluate",
            "skill-backtest",
            "skill-backtest-overfit",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", required=True, help="答案 JSON（枚举值见 question_bank.md）")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument(
        "--mapping",
        default=str(Path(__file__).resolve().parent.parent / "references" / "preference_mapping.yaml"),
        help="映射表路径（默认取本仓库 references/preference_mapping.yaml）",
    )
    args = parser.parse_args()

    mapping = load_mapping(Path(args.mapping))
    raw = json.loads(Path(args.answers).read_text(encoding="utf-8-sig"))
    answers, defaults_used = resolve_answers(raw, mapping)
    derived, flags = derive(answers, mapping)
    user_confirmed = bool(raw.get("user_confirmed", False))

    profile = {
        "schema_version": SCHEMA_VERSION,
        "quiz_version": mapping["quiz_version"],
        "mapping_version": mapping["mapping_version"],
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "answers": answers,
        "derived": derived,
        "defaults_used": defaults_used,
        "consistency_flags": flags,
        "user_confirmed": user_confirmed,
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_path = out_dir / "profile.json"
    profile_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {profile_path} (defaults_used={len(defaults_used)}, flags={len(flags)})")

    if not user_confirmed:
        print("user_confirmed=false: strategy_brief.json not generated; confirm the profile first")
        sys.exit(0)

    brief = build_strategy_brief(derived, mapping, profile_path.name)
    brief_path = out_dir / "strategy_brief.json"
    brief_path.write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {brief_path} (pools={brief['candidate_factor_pools']})")


if __name__ == "__main__":
    main()
