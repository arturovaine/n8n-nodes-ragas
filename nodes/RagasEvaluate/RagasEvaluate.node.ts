import {
  IExecuteFunctions,
  INodeExecutionData,
  INodeType,
  INodeTypeDescription,
  NodeOperationError,
} from 'n8n-workflow';

import { join } from 'path';
import { spawn } from 'child_process';

interface RagasResult {
  results: Array<{ index: number; scores: Record<string, number | null> }>;
  summary: Record<string, number | null>;
  sample_count: number;
}

export class RagasEvaluate implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Ragas Evaluate',
    name: 'ragasEvaluate',
    icon: 'file:ragas.svg',
    group: ['transform'],
    version: 1,
    subtitle: '={{$parameter["metrics"].join(", ")}}',
    description: 'Evaluate RAG outputs with Ragas metrics (faithfulness, relevancy, context quality)',
    defaults: {
      name: 'Ragas Evaluate',
    },
    inputs: ['main'],
    outputs: ['main'],
    credentials: [
      {
        name: 'ragasApi',
        required: false,
      },
    ],
    properties: [
      {
        displayName: 'Metrics',
        name: 'metrics',
        type: 'multiOptions',
        options: [
          {
            name: 'Answer Correctness',
            value: 'answer_correctness',
            description: 'Correctness of the answer against the reference (needs reference)',
          },
          {
            name: 'Answer Relevancy',
            value: 'answer_relevancy',
            description: 'How relevant the answer is to the question (needs embeddings)',
          },
          {
            name: 'Context Precision',
            value: 'context_precision',
            description: 'Whether retrieved contexts are ranked by relevance',
          },
          {
            name: 'Context Recall',
            value: 'context_recall',
            description: 'Whether the contexts cover the reference answer (needs reference)',
          },
          {
            name: 'Faithfulness',
            value: 'faithfulness',
            description: 'Whether the answer is grounded in the retrieved contexts',
          },
          {
            name: 'Semantic Similarity',
            value: 'semantic_similarity',
            description: 'Embedding similarity of answer to reference (needs reference)',
          },
        ],
        default: ['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall'],
        description: 'Ragas metrics to compute for each sample',
        required: true,
      },
      {
        displayName: 'Question Field',
        name: 'questionField',
        type: 'string',
        default: 'question',
        placeholder: 'question',
        description: 'Name of the incoming field holding the user question',
        required: true,
      },
      {
        displayName: 'Answer Field',
        name: 'answerField',
        type: 'string',
        default: 'answer',
        placeholder: 'answer',
        description: 'Name of the incoming field holding the generated answer',
        required: true,
      },
      {
        displayName: 'Contexts Field',
        name: 'contextsField',
        type: 'string',
        default: 'contexts',
        placeholder: 'contexts',
        description: 'Name of the incoming field holding the retrieved contexts (an array, or a string)',
        required: true,
      },
      {
        displayName: 'Reference Field',
        name: 'referenceField',
        type: 'string',
        default: 'reference',
        placeholder: 'reference',
        description:
          'Name of the incoming field holding the ground-truth answer. Required by Context Recall, Answer Correctness and Semantic Similarity. Leave empty if unused.',
      },
      {
        displayName: 'Judge Provider',
        name: 'llmProvider',
        type: 'options',
        options: [
          { name: 'Anthropic', value: 'anthropic' },
          { name: 'Google Gemini', value: 'google' },
          { name: 'Ollama (Local)', value: 'ollama' },
          { name: 'OpenAI', value: 'openai' },
        ],
        default: 'openai',
        description: 'Provider for the judge model that scores the metrics',
      },
      {
        displayName: 'Judge Model',
        name: 'llmModel',
        type: 'string',
        default: 'gpt-4o-mini',
        placeholder: 'gpt-4o-mini',
        description: 'Model name for the judge (e.g. gpt-4o-mini, claude-3-5-sonnet-latest, gemini-1.5-flash)',
      },
      {
        displayName: 'Embeddings Provider',
        name: 'embeddingsProvider',
        type: 'options',
        options: [
          { name: 'Google', value: 'google' },
          { name: 'HuggingFace (Local)', value: 'huggingface' },
          { name: 'Ollama (Local)', value: 'ollama' },
          { name: 'OpenAI', value: 'openai' },
        ],
        default: 'openai',
        description:
          'Provider for embeddings (used by Answer Relevancy and Semantic Similarity). Anthropic has no embeddings API — pair an Anthropic judge with HuggingFace-local or OpenAI embeddings.',
      },
      {
        displayName: 'Embeddings Model',
        name: 'embeddingsModel',
        type: 'string',
        default: 'text-embedding-3-small',
        placeholder: 'text-embedding-3-small',
        description: 'Model name for the embeddings provider',
      },
      {
        displayName: 'Python Path',
        name: 'pythonPath',
        type: 'string',
        default: 'python3',
        description: 'Path to the Python executable with ragas and the provider packages installed',
      },
      {
        displayName: 'Options',
        name: 'options',
        type: 'collection',
        placeholder: 'Add Option',
        default: {},
        options: [
          {
            displayName: 'Contexts Delimiter',
            name: 'contextsDelimiter',
            type: 'string',
            default: '',
            description: 'If the contexts field is a single string, split it into multiple contexts on this delimiter',
          },
          {
            displayName: 'Batch Size',
            name: 'batchSize',
            type: 'number',
            default: 0,
            description: 'Ragas evaluation batch size (0 lets Ragas choose)',
          },
          {
            displayName: 'Request Timeout (Seconds)',
            name: 'timeout',
            type: 'number',
            default: 180,
            description: 'Per-request timeout passed to Ragas',
          },
        ],
      },
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const returnData: INodeExecutionData[] = [];

    const metrics = this.getNodeParameter('metrics', 0) as string[];
    const questionField = this.getNodeParameter('questionField', 0) as string;
    const answerField = this.getNodeParameter('answerField', 0) as string;
    const contextsField = this.getNodeParameter('contextsField', 0) as string;
    const referenceField = this.getNodeParameter('referenceField', 0) as string;
    const llmProvider = this.getNodeParameter('llmProvider', 0) as string;
    const llmModel = this.getNodeParameter('llmModel', 0) as string;
    const embeddingsProvider = this.getNodeParameter('embeddingsProvider', 0) as string;
    const embeddingsModel = this.getNodeParameter('embeddingsModel', 0) as string;
    const pythonPath = this.getNodeParameter('pythonPath', 0) as string;
    const options = this.getNodeParameter('options', 0, {}) as {
      contextsDelimiter?: string;
      timeout?: number;
      batchSize?: number;
    };

    if (metrics.length === 0) {
      throw new NodeOperationError(this.getNode(), 'Select at least one metric to evaluate.');
    }

    let apiKey = '';
    let baseUrl = '';
    try {
      const creds = await this.getCredentials('ragasApi');
      apiKey = (creds.apiKey as string) || '';
      baseUrl = (creds.baseUrl as string) || '';
    } catch {
      // No credential attached — fine for local providers (Ollama, HuggingFace-local).
    }

    const samples = items.map((item) => ({
      question: item.json[questionField] ?? null,
      answer: item.json[answerField] ?? null,
      contexts: item.json[contextsField] ?? null,
      reference: referenceField ? item.json[referenceField] ?? null : null,
    }));

    const payload = {
      config: {
        metrics,
        llm: { provider: llmProvider, model: llmModel, api_key: apiKey, base_url: baseUrl },
        embeddings: {
          provider: embeddingsProvider,
          model: embeddingsModel,
          api_key: apiKey,
          base_url: baseUrl,
        },
        options: {
          contexts_delimiter: options.contextsDelimiter ?? '',
          timeout: options.timeout ?? 180,
          batch_size: options.batchSize ?? 0,
        },
      },
      samples,
    };

    const scriptPath = join(__dirname, 'ragas_runner.py');

    try {
      const raw = await new Promise<string>((resolve, reject) => {
        const python = spawn(pythonPath, [scriptPath]);
        let output = '';
        let errorOutput = '';

        python.stdout.on('data', (data: Buffer) => {
          output += data.toString();
        });
        python.stderr.on('data', (data: Buffer) => {
          errorOutput += data.toString();
        });
        python.on('error', (err: Error) => {
          reject(new Error(`Failed to start Python ('${pythonPath}'): ${err.message}`));
        });
        python.on('close', (code: number) => {
          if (code !== 0) {
            reject(new Error(errorOutput.trim() || `Python exited with code ${code}`));
          } else {
            resolve(output.trim());
          }
        });

        python.stdin.write(JSON.stringify(payload));
        python.stdin.end();
      });

      const parsed = JSON.parse(raw) as RagasResult;

      for (let i = 0; i < items.length; i++) {
        const scores = parsed.results[i]?.scores ?? {};
        returnData.push({
          json: { ...items[i].json, ...scores },
          pairedItem: { item: i },
        });
      }

      returnData.push({
        json: {
          ragas_summary: parsed.summary,
          metrics,
          sample_count: parsed.sample_count,
          judge_model: `${llmProvider}:${llmModel}`,
          embeddings_model: `${embeddingsProvider}:${embeddingsModel}`,
        },
      });
    } catch (error) {
      if (this.continueOnFail()) {
        returnData.push({ json: { error: (error as Error).message } });
      } else {
        throw new NodeOperationError(this.getNode(), (error as Error).message);
      }
    }

    return [returnData];
  }
}
