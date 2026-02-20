import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotPopup } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Agentic Flow Enterprise",
  description: "Advanced GenAI Orchestration with Generative UI",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased max-h-screen bg-gray-50`}
      >
        <CopilotKit publicApiKey="not-needed" runtimeUrl="/api/copilotkit">
          {children}
          <CopilotPopup
            className="fixed bottom-4 right-4 z-50"
            instructions="You are an expert orchestrator assistant."
            labels={{
              title: "Agentic Flow Assistant",
              initial: "How can I help you orchestrate today?",
            }}
          />
        </CopilotKit>
      </body>
    </html>
  );
}
