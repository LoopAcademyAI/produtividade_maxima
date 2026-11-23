"""Servidor MCP do Entrelinhas, servido em /mcp (Streamable HTTP, stateless).

Nota mcp 2.x: FastMCP passou a chamar-se MCPServer (mcp.server.mcpserver).
"""
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

mcp = MCPServer(
    name='entrelinhas',
    instructions='Classifica notas curtas em português numa categoria.',
    version='1.0.0',
)


def _criar_sub_app():
    # stateless_http=True: cada pedido é independente (sem sessões em memória),
    # necessário em serverless (Vercel), onde cada pedido pode cair numa instância diferente.
    # json_response=True: responde com JSON simples em vez de um stream SSE.
    # A proteção contra DNS rebinding do SDK só aceita Host=localhost por defeito, o que
    # rejeitaria o domínio da Vercel; o controlo de acesso é feito pela chave (passo 3).
    return mcp.streamable_http_app(
        streamable_http_path='/mcp',
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


class McpApp:
    """ASGI estável para montar no FastAPI.

    O gestor de sessões do SDK só pode arrancar uma vez por instância, por isso cada
    arranque da aplicação (lifespan) cria um sub-app novo. Em produção isto acontece
    uma vez por processo; nos testes, uma vez por TestClient.
    """

    def __init__(self):
        self._app = None

    @asynccontextmanager
    async def ciclo_de_vida(self):
        self._app = _criar_sub_app()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            self._app = None

    async def __call__(self, scope, receive, send):
        if self._app is None:
            raise RuntimeError('Servidor MCP não iniciado: o lifespan da aplicação não correu.')
        await self._app(scope, receive, send)


mcp_app = McpApp()
