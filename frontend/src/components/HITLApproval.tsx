'use client';

import { useState } from 'react';
import { AgentState } from '@/lib/types';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

export function HITLApproval({
    state,
    onResume,
}: {
    state: AgentState;
    onResume: (action: 'approve' | 'modify' | 'reject', modifiedData?: any) => Promise<void>;
}) {
    const [formData, setFormData] = useState(
        JSON.stringify(state.hitl_context?.args || {}, null, 2)
    );

    if (state.status !== 'SUSPENDED') return null;

    return (
        <Card className="border-amber-500 bg-amber-50/50 shadow-md">
            <CardHeader>
                <CardTitle className="text-amber-700 flex items-center gap-2">
                    <span className="bg-amber-100 p-2 rounded-full">⏸️</span>
                    Approval Required: {state.hitl_context?.reason || 'Operator Intervention'}
                </CardTitle>
            </CardHeader>
            <CardContent>
                <div className="space-y-4">
                    <p className="text-sm text-gray-600">
                        <strong>Agent:</strong> {state.current_agent || 'Unknown'} <br />
                        <strong>Suspended At:</strong> {state.hitl_context?.suspended_at}
                    </p>
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Tool Execution Parameters:</label>
                        <textarea
                            className="w-full h-32 p-3 text-sm font-mono border rounded-md"
                            value={formData}
                            onChange={(e) => setFormData(e.target.value)}
                        />
                    </div>
                </div>
            </CardContent>
            <CardFooter className="flex gap-2">
                <Button
                    variant="default"
                    className="bg-green-600 hover:bg-green-700 text-white"
                    onClick={() => onResume('approve')}
                >
                    Approve (As-Is)
                </Button>
                <Button
                    variant="secondary"
                    className="bg-blue-600 hover:bg-blue-700 text-white"
                    onClick={() => {
                        try {
                            const parsed = JSON.parse(formData);
                            onResume('modify', parsed);
                        } catch (e) {
                            alert('Invalid JSON parameters');
                        }
                    }}
                >
                    Modify & Resume
                </Button>
                <Button
                    variant="destructive"
                    onClick={() => onResume('reject')}
                >
                    Reject
                </Button>
            </CardFooter>
        </Card>
    );
}
