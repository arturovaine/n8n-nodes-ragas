import { ICredentialType, INodeProperties } from 'n8n-workflow';

export class RagasApi implements ICredentialType {
  name = 'ragasApi';

  displayName = 'Ragas API';

  documentationUrl = 'https://github.com/arturovaine/n8n-nodes-ragas';

  properties: INodeProperties[] = [
    {
      displayName: 'API Key',
      name: 'apiKey',
      type: 'string',
      typeOptions: {
        password: true,
      },
      default: '',
      description:
        'API key for the judge and embeddings provider. Leave empty for local providers such as Ollama or HuggingFace-local.',
    },
    {
      displayName: 'Base URL',
      name: 'baseUrl',
      type: 'string',
      default: '',
      placeholder: 'http://localhost:11434/v1',
      description:
        'Optional custom base URL for OpenAI-compatible or local endpoints (for example an Ollama server).',
    },
  ];
}
