import {
  FileText,
  Home,
  MessageSquare,
  Shield,
  Upload,
} from "lucide-react";

import { NavLink } from "react-router-dom";

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

import worldlineLogo from "@/assets/worldline-logo.svg";


const navItems = [
  {
    title: "Dashboard",
    url: "/",
    icon: Home,
  },
  {
    title: "Upload Contract",
    url: "/upload",
    icon: Upload,
  },
  {
    title: "Policy Library",
    url: "/policies",
    icon: Shield,
  },
  {
    title: "Analyses",
    url: "/analyses",
    icon: FileText,
  },
  {
    title: "Ask AI",
    url: "/chat",
    icon: MessageSquare,
  },
];


export function AppSidebar() {
  return (
    <Sidebar collapsible="icon">
      <SidebarContent>
        <div className="border-b border-sidebar-border p-4">
          < img src={worldlineLogo} alt="Worldline" className="h-8 w-auto" / >        </div>

        <SidebarGroup>
          <SidebarGroupLabel className="text-sidebar-foreground/60">
            Contract Derisking
          </SidebarGroupLabel>

          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton
                    asChild
                    tooltip={item.title}
                  >
                    <NavLink
                      to={item.url}
                      end
                      className={({ isActive }) =>
                        isActive
                          ? "bg-sidebar-accent"
                          : ""
                      }
                    >
                      <item.icon />
                      <span>{item.title}</span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}