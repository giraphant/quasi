export const meta = {
  name: 'codex-smoke',
  description: 'Exercise one structured Codex worker without touching vault files',
}

return agent(
  'Return a JSON receipt with status "ok" and runtime "codex". Do not call tools.',
  {
    agentType: 'general-purpose',
    label: 'codex-smoke',
    schema: {
      type: 'object',
      required: ['status', 'runtime'],
      properties: {
        status: { type: 'string', enum: ['ok'] },
        runtime: { type: 'string', enum: ['codex'] },
        note: { type: 'string' },
      },
    },
  },
)
