'use client';

import { useCopilotReadable } from "@copilotkit/react-core";
import { useState, useEffect } from "react";
import { AgentState, HITL_POLL_INTERVAL, API_BASE_URL } from "@/lib/types";
import { HITLApproval } from "@/components/HITLApproval";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, Server, AlertCircle } from "lucide-react";

export default function Dashboard() {
  const [agentState, setAgentState] = useState<AgentState | null>(null);

  // Sync state to CopilotKit context so the LLM knows the current UI state
  useCopilotReadable({
    description: "The current state of the Clawflow orchestration system",
    value: agentState,
  });

  // Poll for agent state changes
  useEffect(() => {
    const fetchState = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/conversations/current`);
        if (res.ok) {
          const data = await res.json();
          setAgentState(data);
        }
      } catch (e) {
        console.error("Failed to fetch agent state:", e);
      }
    };

    fetchState();
    const interval = setInterval(fetchState, HITL_POLL_INTERVAL);
    return () => clearInterval(interval);
  }, []);

  const handleResume = async (action: 'approve' | 'modify' | 'reject', modifiedData?: any) => {
    if (!agentState?.session_id) return;
    try {
      if (action === 'reject') {
        await fetch(`${API_BASE_URL}/conversations/halt`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ thread_id: agentState.session_id, reason: 'Operator rejected pending action' })
        });
      } else {
        await fetch(`${API_BASE_URL}/conversations/resume`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            thread_id: agentState.session_id,
            action,
            modified_data: modifiedData
          })
        });
      }
      // Optimistic update
      setAgentState(prev => prev ? { ...prev, status: 'RUNNING' } : null);
    } catch (e) {
      console.error("Failed to resume:", e);
      alert("Failed to send resume signal.");
    }
  };

  return (
    <main className="container mx-auto p-8 pt-12 max-w-5xl">
      <div className="flex flex-col gap-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-900">Clawflow Dashboard</h1>
            <p className="text-slate-500 mt-1">Enterprise Hybrid AI Orchestration</p>
          </div>
          <div className="flex items-center gap-2 bg-white px-4 py-2 rounded-full border shadow-sm">
            <div className={`w-3 h-3 rounded-full ${agentState?.status === 'RUNNING' ? 'bg-green-500 animate-pulse' : agentState?.status === 'SUSPENDED' ? 'bg-amber-500' : 'bg-slate-300'}`} />
            <span className="text-sm font-medium uppercase tracking-wider text-slate-700">
              {agentState?.status || 'DISCONNECTED'}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-slate-500">Active Persona</CardTitle>
              <Activity className="h-4 w-4 text-slate-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{agentState?.active_persona || 'None'}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-slate-500">Current Agent</CardTitle>
              <Server className="h-4 w-4 text-slate-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold capitalize">{agentState?.current_agent || 'Routing'}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-slate-500">Execution Step</CardTitle>
              <AlertCircle className="h-4 w-4 text-slate-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{agentState?.step || 0}</div>
            </CardContent>
          </Card>
        </div>

        {/* Human-in-the-Loop Gateway */}
        {agentState?.status === 'SUSPENDED' && (
          <div className="mt-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <HITLApproval state={agentState} onResume={handleResume} />
          </div>
        )}

      </div>
    </main>
  );
}
