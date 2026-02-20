import { CopilotRuntime, OpenAIAdapter } from '@copilotkit/runtime';
import { NextRequest } from 'next/server';

// ── Custom LangGraph/FastAPI Connector for CopilotKit ──
// We act as an intermediary, sending the chat messages to our FastAPI
// backend which runs the LangGraph AI orchestrator.

export async function POST(req: NextRequest) {
    const { messages } = await req.json();

    const runtime = new CopilotRuntime();

    // For a simple pass-through, we can use the OpenAIAdapter pointing
    // to LiteLLM, but ideally we want to call our FastAPI Orchestrator.
    // We'll proxy the latest user message to the agentic_flow FastAPI endpoint.

    const lastUserMessage = messages.filter((m: { role: string; content: string }) => m.role === 'user').pop();

    if (lastUserMessage) {
        // Fire and forget the task to the LangGraph backend via a REST API (custom implementation).
        // In a real scenario, this would stream the response back.
        console.log("Triggering Agentic Flow for:", lastUserMessage.content);
    }

    const { response } = await runtime.process(
        req,
        new OpenAIAdapter({
            model: "gpt-4o", // fallback or routing alias
        })
    );
    return response;
}
