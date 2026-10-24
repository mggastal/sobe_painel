/* Painel Sobé — servidor do Admin (Cloudflare Worker).
 *
 * Mesma ideia do Worker do mapa mental: a equipe entra com usuário e senha,
 * e o Worker grava clientes.json no repo sobe_painel com um token do GitHub
 * que fica só aqui (ninguém precisa de token no navegador).
 *
 * Variáveis (Settings → Variables and Secrets):
 *   GITHUB_TOKEN    secret · fine-grained, só o repo sobe_painel: Contents RW + Actions RW
 *   USUARIO_EQUIPE  texto  · o mesmo do mapa mental
 *   SENHA_EQUIPE    secret · a mesma do mapa mental
 *   REPO            texto  · mggastal/sobe_painel
 *   ORIGENS         texto  · https://mggastal.github.io  (vírgula para mais de uma)
 *
 * Rotas:
 *   GET  /            status do serviço
 *   POST /login       {usuario, senha, nome} -> {token, nome}
 *   PUT  /clientes    {cadastro}  (header X-Sobe-Sessao) grava clientes.json e dispara a coleta
 *   POST /coletar     (header X-Sobe-Sessao) dispara a coleta agora
 */

const VALIDADE_DIAS = 30;
const STATUS_OK = ["ativo", "pausado", "arquivado"];

export default {
  async fetch(req, env) {
    const cors = corsHeaders(req, env);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    const url = new URL(req.url);
    const json = (obj, status = 200) =>
      new Response(JSON.stringify(obj), { status, headers: { ...cors, "Content-Type": "application/json" } });

    try {
      if (url.pathname === "/" && req.method === "GET") {
        return json({
          ok: true, servico: "sobe-painel", REPO: env.REPO || "",
          GITHUB_TOKEN: env.GITHUB_TOKEN ? "definido" : "FALTANDO",
          SENHA_EQUIPE: env.SENHA_EQUIPE ? "definida" : "FALTANDO",
        });
      }

      if (url.pathname === "/login" && req.method === "POST") {
        const b = await req.json().catch(() => ({}));
        const okUser = !env.USUARIO_EQUIPE || igual(String(b.usuario || "").trim().toLowerCase(), String(env.USUARIO_EQUIPE).trim().toLowerCase());
        if (!env.SENHA_EQUIPE || !okUser || !igual(String(b.senha || ""), String(env.SENHA_EQUIPE))) {
          await new Promise(r => setTimeout(r, 600));
          return json({ error: "Usuário ou senha incorretos." }, 401);
        }
        const nome = String(b.nome || b.usuario || "equipe").slice(0, 40);
        return json({ token: await assinar(env, nome), nome });
      }

      const sessao = await verificar(env, req.headers.get("X-Sobe-Sessao") || "");
      if (!sessao) return json({ error: "sessao" }, 401);

      if (url.pathname === "/clientes" && req.method === "PUT") {
        const b = await req.json().catch(() => null);
        const erro = validar(b && b.cadastro);
        if (erro) return json({ error: erro }, 400);
        const caminho = `/repos/${env.REPO}/contents/clientes.json`;
        const atual = await gh(env, caminho);
        const texto = JSON.stringify(b.cadastro, null, 2) + "\n";
        await gh(env, caminho, "PUT", {
          message: `Painel: cadastro atualizado por ${sessao.nome}`,
          content: b64(texto),
          sha: atual.sha,
        });
        const coleta = await disparar(env);
        return json({ ok: true, coleta });
      }

      if (url.pathname === "/coletar" && req.method === "POST") {
        return json({ ok: true, coleta: await disparar(env) });
      }

      return json({ error: "rota não encontrada" }, 404);
    } catch (e) {
      return json({ error: String(e.message || e).slice(0, 200) }, 500);
    }
  },
};

function corsHeaders(req, env) {
  const origem = req.headers.get("Origin") || "";
  const permitidas = String(env.ORIGENS || "https://mggastal.github.io").split(",").map(s => s.trim());
  const ok = permitidas.includes(origem) || /^http:\/\/localhost(:\d+)?$/.test(origem);
  return {
    "Access-Control-Allow-Origin": ok ? origem : permitidas[0],
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Sobe-Sessao",
    "Vary": "Origin",
  };
}

function validar(c) {
  if (!c || typeof c !== "object" || !Array.isArray(c.clientes)) return "cadastro inválido";
  if (JSON.stringify(c).length > 200000) return "cadastro grande demais";
  const repos = new Set();
  for (const x of c.clientes) {
    if (!x || !/^[\w.-]+$/.test(x.repo || "")) return "repo inválido: " + (x && x.repo);
    if (repos.has(x.repo)) return "repo repetido: " + x.repo;
    repos.add(x.repo);
    if (!STATUS_OK.includes(x.status)) return "status inválido em " + x.repo;
  }
  return null;
}

async function gh(env, caminho, method = "GET", body) {
  const r = await fetch("https://api.github.com" + caminho, {
    method,
    headers: {
      "Authorization": "Bearer " + env.GITHUB_TOKEN,
      "Accept": "application/vnd.github+json",
      "User-Agent": "sobe-painel-worker",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok && r.status !== 204) throw new Error("GitHub " + r.status + " " + (await r.text()).slice(0, 120));
  return r.status === 204 ? {} : r.json();
}

async function disparar(env) {
  try {
    await gh(env, `/repos/${env.REPO}/actions/workflows/coletar.yml/dispatches`, "POST", { ref: "main" });
    return "disparada";
  } catch (e) {
    return "não disparada (" + String(e.message).slice(0, 60) + ")";
  }
}

/* ---------- sessão: token assinado (HMAC), sem banco ---------- */
async function chave(env) {
  return crypto.subtle.importKey("raw", new TextEncoder().encode("sobe-painel|" + env.SENHA_EQUIPE),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
}
async function hmac(env, txt) {
  const sig = await crypto.subtle.sign("HMAC", await chave(env), new TextEncoder().encode(txt));
  return btoa(String.fromCharCode(...new Uint8Array(sig))).replace(/[+/=]/g, c => ({ "+": "-", "/": "_", "=": "" }[c]));
}
async function assinar(env, nome) {
  const corpo = b64(JSON.stringify({ nome, exp: Date.now() + VALIDADE_DIAS * 864e5 }));
  return corpo + "." + await hmac(env, corpo);
}
async function verificar(env, token) {
  const [corpo, sig] = String(token).split(".");
  if (!corpo || !sig || !env.SENHA_EQUIPE) return null;
  if (!igual(sig, await hmac(env, corpo))) return null;
  try {
    const d = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(corpo), c => c.charCodeAt(0))));
    return d.exp > Date.now() ? d : null;
  } catch (e) { return null; }
}
function igual(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
function b64(txt) {
  return btoa(String.fromCharCode(...new TextEncoder().encode(txt)));
}
