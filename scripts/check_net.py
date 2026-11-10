"""Quick self-test: can THIS Python reach DeepSeek and the TTS service?  Run:  python scripts\\check_net.py"""
import asyncio, os, socket, sys

def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def ok(name, good, extra=""):
    print(("PASS  " if good else "FAIL  ") + name + (("  -> " + extra) if extra else ""))
    return good

load_env()
print("1) DNS (does Python resolve these names?)")
for host in ["google.com", "api.deepseek.com", "speech.platform.bing.com"]:
    try:
        socket.getaddrinfo(host, 443); ok(host, True)
    except Exception as e:
        ok(host, False, str(e))

async def main():
    import httpx
    print("\n2) DeepSeek API call")
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        ok("DEEPSEEK_API_KEY in .env", False, "missing - add it to .env"); return
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.post("https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "deepseek-flash", "max_tokens": 20,
                      "messages": [{"role": "user", "content": "Say hi in 3 words."}]})
        txt = r.text[:200].replace("\n", " ")
        ok("DeepSeek reply", r.status_code == 200, f"HTTP {r.status_code} {txt}")
    except Exception as e:
        ok("DeepSeek reachable", False, str(e))
    print("\n3) Voice (edge-tts)")
    try:
        import edge_tts
        await asyncio.wait_for(edge_tts.Communicate("Hello from Hubie", "en-GB-RyanNeural").save("cache/_test.mp3"), 25)
        ok("edge-tts made cache/_test.mp3", os.path.getsize("cache/_test.mp3") > 1000)
    except Exception as e:
        ok("edge-tts", False, str(e))

asyncio.run(main())
print("\nIf DNS lines FAIL: change Windows DNS to 1.1.1.1 / 8.8.8.8, turn off VPN/proxy tricks, allow python.exe in firewall.")
