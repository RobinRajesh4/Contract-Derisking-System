import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import {
  BrowserRouter,
  Routes,
  Route,
} from "react-router-dom";
import {
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import Dashboard from "./pages/Dashboard";
import Upload from "./pages/Upload";
import Policies from "./pages/Policies";
import Analyses from "./pages/Analyses";
import AnalysisDetail from "./pages/AnalysisDetail";
import Insights from "./pages/Insights";
import Compare from "./pages/Compare";
import NotFound from "./pages/NotFound";
import worldlineLogo from "@/assets/worldline-logo.svg";
import Chat from "./pages/Chat";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <SidebarProvider>
          <div className="flex min-h-screen w-full">
            <AppSidebar />

            <main className="flex-1 overflow-auto">
              <header className="sticky top-0 z-10 flex h-14 items-center gap-4 border-b bg-background px-6">
                <SidebarTrigger />

                <div>
                  < img src={worldlineLogo} alt="Worldline" className="h-6 w-auto" / >
                </div>

                <h2 className="text-lg font-semibold">
                  Contract Derisking System
                </h2>
              </header>

              <div className="p-6">
                <Routes>
                  <Route
                    path="/chat"
                    element={<Chat />}
                  />

                  <Route
                    path="/"
                    element={<Dashboard />}
                  />

                  <Route
                    path="/upload"
                    element={<Upload />}
                  />

                  <Route
                    path="/policies"
                    element={<Policies />}
                  />

                  <Route
                    path="/analyses"
                    element={<Analyses />}
                  />

                  <Route
                    path="/analyses/:id"
                    element={<AnalysisDetail />}
                  />

                  <Route
                    path="/insights"
                    element={<Insights />}
                  />

                  <Route
                    path="/compare"
                    element={<Compare />}
                  />

                  <Route
                    path="*"
                    element={<NotFound />}
                  />
                </Routes>
              </div>
            </main>
          </div>
        </SidebarProvider>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;