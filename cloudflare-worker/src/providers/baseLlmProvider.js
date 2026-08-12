import { IntentType } from "../types/intentTypes.js";

/**
 * Base Abstract LLM Provider Interface / Contract.
 * Custom LLM providers (Gemini, OpenAI, Anthropic, etc.) must extend this class.
 */
export class BaseLlmProvider {
  /**
   * Classifies user intent for a given repository and prompt.
   * @param {Object} params - { repo, prompt }
   * @returns {Promise<{ intent: keyof typeof IntentType, question: string }>}
   */
  async classifyIntent({ repo, prompt }) {
    throw new Error("classifyIntent() must be implemented by subclass.");
  }
}
