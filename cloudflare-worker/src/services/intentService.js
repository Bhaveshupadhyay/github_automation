import { IntentType } from "../types/intentTypes.js";

/**
 * Service to handle intent classification and fast-path decision making.
 * Depends on BaseLlmProvider abstraction for clean architecture.
 */
export class IntentService {
  /**
   * @param {import("../providers/baseLlmProvider.js").BaseLlmProvider} llmProvider 
   */
  constructor(llmProvider) {
    this.llmProvider = llmProvider;
  }

  /**
   * Evaluates intent for given repository prompt.
   * @param {string} repo 
   * @param {string} prompt 
   * @returns {Promise<{ intent: keyof typeof IntentType, question: string }>}
   */
  async evaluateIntent(repo, prompt) {
    if (!this.llmProvider) {
      console.warn("[IntentService] No LLM provider injected. Defaulting to CODE_DEVELOPMENT.");
      return { intent: IntentType.CODE_DEVELOPMENT, question: "" };
    }
    return await this.llmProvider.classifyIntent({ repo, prompt });
  }
}
