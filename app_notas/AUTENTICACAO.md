# R1.2 — opções de autenticação

## Contexto

Atualmente, o browser guarda um UUID no `localStorage` e envia-o em `X-Utilizador`.
Este UUID separa os registos, mas não autentica a pessoa: quem obtiver o valor pode
fazer pedidos como esse utilizador.

Este documento compara mecanismos de autenticação que podem ser usados sem custo
direto de serviço para a escala atual do projeto. **Não escolhe uma opção.** A equipa
vai tomar essa decisão depois de rever as alternativas. Este ticket não implementa
autenticação nem altera código, API, base de dados ou interface.

## O que significa «custo 0 €»

As opções abaixo podem ser experimentadas sem contratar um plano pago, desde que se
mantenham dentro dos limites gratuitos dos fornecedores e da infraestrutura já usada
pela aplicação. Não se contabiliza o esforço de trabalho. Limites, condições de conta,
verificação de domínio e disponibilidade dos planos gratuitos podem mudar; devem ser
confirmados antes de implementar. Se uma opção exigir pagamento ou cartão para o uso
pretendido, deixa de cumprir o requisito de 0 €.

Não existe uma lista literalmente exaustiva de todos os mecanismos possíveis. Esta
comparação cobre as alternativas práticas mais relevantes para a aplicação atual.

## Comparação

| Opção | Custo direto previsto | Esforço | Privacidade | Experiência | Limites e riscos |
|---|---|---|---|---|---|
| **Magic link por email** | 0 € se um fornecedor de email/SMTP oferecer quota gratuita suficiente; confirmar limites e se exige cartão | Médio: envio de email, token aleatório de uso único, expiração, consumo atómico, sessão, rate limiting e recuperação | A aplicação processa o email; o fornecedor recebe endereço e metadados de entrega | Simples, sem password nem conta num fornecedor de login; depende de acesso ao email e entrega atempada | Spam, atrasos, quota gratuita, abuso de envio e recuperação de conta |
| **OAuth com GitHub ou Google** | 0 € para o fluxo de login standard nos planos gratuitos; confirmar condições atuais | Médio: registar OAuth app, callbacks, `state` anti-CSRF, sessão e configuração por ambiente | O fornecedor recebe dados do login; limitar scopes e guardar apenas identificador necessário | Rápido para quem já tem uma conta suportada; exclui ou acrescenta fricção a quem não a usa | Dependência e disponibilidade do fornecedor; mudanças de política; utilizadores sem conta compatível |
| **Passkeys / WebAuthn** | 0 € de fornecedor de login; usa APIs de browser/dispositivo e a infraestrutura atual | Médio/alto: desafios WebAuthn, registo de credenciais, validação, recuperação e compatibilidade entre dispositivos | Não exige enviar password a um fornecedor; credencial é ligada ao autenticador. A aplicação ainda mantém identificador de conta | Login rápido com biometria/PIN e resistente a phishing em dispositivos compatíveis | Recuperação e troca de dispositivo são difíceis; compatibilidade e UX têm de ser testadas |
| **Password gerida pela aplicação** | 0 € de serviço de identidade; reset por email só é 0 € se houver envio gratuito | Alto: hashing seguro, política de passwords, reset, proteção contra brute force, sessões, recuperação e suporte | Credenciais ficam sob responsabilidade da aplicação; guardar apenas hash com algoritmo adequado | Familiar, mas exige criar e memorizar password; reset adiciona passos | Maior responsabilidade e superfície de segurança; uma falha expõe contas; emails de recuperação podem ter custo |
| **Chave pessoal por utilizador** | 0 € de serviço; pode ser gerada e verificada pela aplicação | Baixo para uma demo; médio para gestão, revogação, rotação e sessões seguras | A chave é um segredo bearer; quem a obtiver pode usá-la. Não prova identidade por si só | Fraca: utilizador tem de copiar e guardar uma chave; recuperação é difícil | Fácil de partilhar, perder ou expor; não é recomendada para proteger notas privadas |

## Notas por opção

### Magic link por email

O utilizador pede um link para o seu endereço. A aplicação gera um token imprevisível,
de curta duração e uso único, guarda apenas o hash, e envia o link. Ao ser usado, o
token é consumido atomicamente e inicia uma sessão revogável.

O custo é 0 € apenas se existir um fornecedor de email com quota adequada sem cartão
ou upgrade pago. A equipa deve verificar quota, limites de envio, verificação do
domínio, retenção e tratamento de bounces. Nunca registar o endereço, o token nem o
link completo.

### OAuth com GitHub ou Google

O utilizador autoriza o fornecedor e regressa por callback. A aplicação valida `state`,
identifica a conta pelo identificador estável do fornecedor e cria uma sessão própria.
Não pedir scopes além da identidade mínima.

O login costuma ser gratuito, mas associa a disponibilidade de acesso à conta externa.
GitHub e Google são fornecedores alternativos, não uma autenticação controlada pela
aplicação.

### Passkeys / WebAuthn

O browser e o autenticador do dispositivo provam a posse de uma credencial
criptográfica. O servidor guarda a credencial pública e verifica desafios assinados.
O segredo privado não é enviado à aplicação.

Não há custo de fornecedor no fluxo base, mas recuperação, sincronização entre
dispositivos e suporte a browsers são decisões importantes. O utilizador pode perder
acesso se não tiver um método de recuperação aprovado.

### Password gerida pela aplicação

A aplicação gere o ciclo completo das credenciais. O custo de software pode ser 0 €,
mas aumenta significativamente a responsabilidade operacional e de segurança. Deve
usar hashing de passwords apropriado, rate limiting, recuperação segura e sessões com
expiração/revogação. Não guardar passwords em texto simples ou reversível.

### Chave pessoal

Uma chave aleatória pode restringir acesso em demonstrações pequenas, mas funciona como
segredo partilhado: a posse da chave basta para agir como o utilizador. É mais próxima
de uma credencial API do que de login de pessoa. Não resolve bem recuperação, perda,
partilha ou exposição.

## Sessão e isolamento — requisitos comuns

Independentemente da opção selecionada, a futura implementação deve:

- derivar a identidade no servidor a partir de uma autenticação validada;
- deixar de confiar num `X-Utilizador` arbitrário como prova de identidade;
- proteger criar, listar, procurar, importar e apagar notas;
- impedir que um utilizador leia ou altere notas de outro;
- usar sessões com expiração e revogação, em cookies `HttpOnly`, `SameSite=Lax` e
  `Secure` em produção, se o fluxo usar cookies;
- não registar texto das notas, emails, passwords, tokens, links, cookies ou segredos;
- definir uma migração segura das notas atuais por UUID, sem permitir apropriação por
  alguém que apenas conheça ou adivinhe esse UUID.

## Decisão

**Pendente.** Este ticket não escolhe magic link, OAuth, passkeys, passwords nem chave
pessoal. A equipa deve selecionar uma opção após comparar o custo realmente disponível,
o esforço de suporte, os requisitos de privacidade e a experiência dos utilizadores.
Depois da decisão, deve ser criado o ticket de implementação correspondente com
critérios de aceitação próprios.
