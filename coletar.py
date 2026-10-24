"""Coletor do Painel Sobé.

Lê (somente leitura) o data.json publicado de cada dash em clientes.json e o
status da última GitHub Action de cada repo, e grava status.json — um resumo
pequeno e no mesmo formato para todos os clientes. Não altera nada nos repos
dos clientes.

Uso:  python3 coletar.py            (GITHUB_TOKEN opcional, evita limite da API)
"""
import json
import os
import re
import ssl
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

PAGES = "https://mggastal.github.io"
DONO = "mggastal"
DIAS_SERIE = 120          # dias diários guardados por cliente
MESES = 12
BRT = timezone(timedelta(hours=-3))

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl.create_default_context()


def baixar(url, api=False):
    h = {"User-Agent": "sobe-painel"}
    if api:
        h["Accept"] = "application/vnd.github+json"
        if os.environ.get("GITHUB_TOKEN"):
            h["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=90, context=CTX) as r:
        return r.read().decode("utf-8")


def iso(d):
    """'23/10/2026' ou '2026-10-23' -> '2026-10-23'."""
    d = str(d)[:10]
    if "/" in d:
        dd, mm, aa = d.split("/")
        return f"{aa}-{mm}-{dd}"
    return d


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------- leitores por formato: devolvem {plataforma: {dia: [spend, conv]}} ----------

def do_template(d, acc=None):
    acc = acc if acc is not None else defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    md = d.get("META_DAILY") or {}
    m = md.get("all") or md.get("lct") or {}
    for i, dia in enumerate(m.get("days") or []):
        s = acc["meta"][iso(dia)]
        s[0] += num((m.get("spend") or [0])[i] if i < len(m.get("spend") or []) else 0)
        s[1] += num((m.get("leads") or [0])[i] if i < len(m.get("leads") or []) else 0)
    if d.get("USAR_GOOGLE"):
        g = d.get("GOOGLE_DAILY") or {}
        for i, dia in enumerate(g.get("days") or []):
            s = acc["google"][iso(dia)]
            s[0] += num(g["spend"][i] if i < len(g.get("spend") or []) else 0)
            s[1] += num(g["conversions"][i] if i < len(g.get("conversions") or []) else 0)
    return acc


def do_cidades(d):
    acc = None
    for chave in (d.get("_META") or {}).get("cidades", {}):
        if chave in d:
            acc = do_template(d[chave], acc)
    return acc


def do_unibrasil(d):
    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for r in d.get("meta") or []:
        s = acc["meta"][iso(r["d"])]
        s[0] += num(r.get("sp")); s[1] += num(r.get("ld"))
    for r in d.get("google") or []:
        s = acc["google"][iso(r["d"])]
        s[0] += num(r.get("sp")); s[1] += num(r.get("cv"))
    return acc


def extrair_const(html, nome):
    m = re.search(r"const\s+" + nome + r"\s*=\s*", html)
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(html, m.end())[0]
    except ValueError:
        return None


def do_embed(html):
    d = {k: extrair_const(html, k) for k in ("META_DAILY", "GOOGLE_DAILY", "USAR_GOOGLE")}
    return do_template(d), extrair_const(html, "DATA_GERACAO")


# ---------- montagem ----------

def resumir(acc):
    """Série diária (meta+google somados e por plataforma) e meses."""
    if not acc:
        return None
    dias = sorted({dia for p in acc.values() for dia in p})
    if not dias:
        return None
    ultimo = dias[-1]
    # a janela termina hoje (BRT) para todos: conta parada aparece com zeros
    fim = max(datetime.fromisoformat(ultimo), datetime.now(BRT).replace(tzinfo=None))
    janela = [(fim - timedelta(days=i)).date().isoformat() for i in range(DIAS_SERIE - 1, -1, -1)]
    plats = sorted(acc)
    serie = {"dias": janela}
    for p in plats:
        serie[p] = [[round(acc[p][dia][0], 2), round(acc[p][dia][1], 1)] if dia in acc[p] else [0, 0] for dia in janela]
    meses = defaultdict(lambda: [0.0, 0.0])
    por_plat = defaultdict(lambda: defaultdict(float))
    for p in plats:
        for dia, (sp, cv) in acc[p].items():
            meses[dia[:7]][0] += sp
            meses[dia[:7]][1] += cv
            por_plat[p][dia[:7]] += sp
    ult_meses = sorted(meses)[-MESES:]
    return {
        "ultimo_dia": ultimo,
        "plataformas": plats,
        "serie": serie,
        "meses": [[m, round(meses[m][0], 2), round(meses[m][1], 1)] for m in ult_meses],
        "meses_plat": {p: {m: round(por_plat[p][m], 2) for m in ult_meses if por_plat[p][m]} for p in plats},
    }


def workflow(repo):
    try:
        runs = json.loads(baixar(f"https://api.github.com/repos/{DONO}/{repo}/actions/runs?per_page=10", api=True))
    except Exception as e:
        return {"erro": str(e)[:120]}
    for r in runs.get("workflow_runs") or []:
        if r.get("event") == "dynamic":      # deploy do Pages, não é o gerador
            continue
        return {
            "nome": r.get("name"),
            "status": r.get("status"),
            "conclusao": r.get("conclusion"),
            "quando": r.get("updated_at"),
            "url": r.get("html_url"),
        }
    return None


def coletar(c):
    repo, fmt = c["repo"], c.get("formato", "template")
    out = {"formato": fmt}
    try:
        if fmt == "embed":
            html = baixar(f"{PAGES}/{repo}/")
            acc, gerado = do_embed(html)
            out.update(resumir(acc) or {})
            out["gerado"] = gerado
        else:
            d = json.loads(baixar(f"{PAGES}/{repo}/data.json"))
            if fmt == "resumo":
                out["lancamento"] = {
                    "cod": d.get("lancamento") or "",
                    "kpis": d.get("kpis") or {},
                }
                out["gerado"] = d.get("atualizado")
            elif fmt == "unibrasil":
                out.update(resumir(do_unibrasil(d)) or {})
                out["gerado"] = d.get("gerado_em")
            elif fmt == "cidades":
                out.update(resumir(do_cidades(d)) or {})
                cid = d.get((d.get("_META") or {}).get("cidade_padrao")) or {}
                out["gerado"] = cid.get("DATA_GERACAO")
                out["moeda"] = cid.get("MOEDA_SIMBOLO")
            else:
                out.update(resumir(do_template(d)) or {})
                out["gerado"] = d.get("DATA_GERACAO")
                out["moeda"] = d.get("MOEDA_SIMBOLO")
                if d.get("LANCAMENTO_COD"):
                    out["lancamento"] = {"cod": d["LANCAMENTO_COD"], "kpis": {}}
        out["ok"] = True
    except Exception as e:
        out["ok"] = False
        out["erro"] = f"{type(e).__name__}: {str(e)[:160]}"
    out["workflow"] = workflow(repo)
    return out


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    cad = json.load(open(os.path.join(base, "clientes.json"), encoding="utf-8"))
    res = {}
    for c in cad["clientes"]:
        res[c["repo"]] = coletar(c)
        r = res[c["repo"]]
        print(f"{c['repo']:<22} {'ok ' if r['ok'] else 'ERRO'} ultimo={r.get('ultimo_dia', '-')} "
              f"wf={(r.get('workflow') or {}).get('conclusao')}", r.get("erro", ""))
    status = {"gerado_em": datetime.now(BRT).isoformat(timespec="seconds"), "clientes": res}
    with open(os.path.join(base, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, separators=(",", ":"))
    print("status.json:", os.path.getsize(os.path.join(base, "status.json")) // 1024, "KB")


if __name__ == "__main__":
    sys.exit(main())
