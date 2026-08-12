import { BaseLlmProvider } from "./baseLlmProvider.js";
import { IntentType } from "../types/intentTypes.js";

/**
 * Gemini LLM Provider implementation using Gemini 3.1 Flash Lite REST API.
 */
export class GeminiProvider extends BaseLlmProvider {
  constructor(apiKey, model = "gemini-3.1-flash-lite") {
    super();
    this.apiKey = apiKey;
    this.model = model;
  }

  async classifyIntent({ repo, prompt }) {
    if (!this.apiKey) {
      console.warn("[GeminiProvider] API key missing. Defaulting intent to CODE_DEVELOPMENT.");
      return { intent: IntentType.CODE_DEVELOPMENT, question: "" };
    }

    const url = `https://generativelanguage.googleapis.com/v1beta/models/${this.model}:generateContent?key=${this.apiKey}`;
    
    const systemInstruction = 
      "You are an intent classifier for an automated AI software developer agent. " +
      "Analyze the user's request. If the prompt specifies a clear coding task or instruction, " +
      `respond with JSON: {"intent": "${IntentType.CODE_DEVELOPMENT}"}.\n` +
      "If the prompt is missing vital information (e.g. asking to change an app name without specifying what name to use), " +
      `respond with JSON: {"intent": "${IntentType.CLARIFICATION_NEEDED}", "question": "<1-sentence polite clarification question>"}`;

    const userContent = `Target Repository: ${repo}\nUser Prompt: ${prompt}`;

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: `${systemInstruction}\n\n${userContent}` }] }],
          generationConfig: { responseMimeType: "application/json" }
        })
      });

      if (!response.ok) {
        console.error(`[GeminiProvider] API request failed with status ${response.status}`);
        return { intent: IntentType.CODE_DEVELOPMENT, question: "" };
      }

      const data = await response.json();
      const text = data.candidates?.[0]?.content?.parts?.[0]?.text;
      if (text) {
        const parsed = JSON.parse(text);
        return {
          intent: parsed.intent === IntentType.CLARIFICATION_NEEDED ? IntentType.CLARIFICATION_NEEDED : IntentType.CODE_DEVELOPMENT,
          question: parsed.question || ""
        };
      }
    } catch (err) {
      console.error("[GeminiProvider] Error during classification:", err);
    }

    return { intent: IntentType.CODE_DEVELOPMENT, question: "" };
  }
}
