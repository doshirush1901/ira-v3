"use client";

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import PipelineBoard from "@/components/PipelineBoard";
import VendorTable from "@/components/VendorTable";
import EmailSearch from "@/components/EmailSearch";

export default function CRMPage() {
  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">
            CRM & Vendor Dashboard
          </h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Pipeline, vendor payables, and email search
          </p>
        </div>

        <Tabs defaultValue="pipeline">
          <TabsList>
            <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
            <TabsTrigger value="vendors">Vendor Payables</TabsTrigger>
            <TabsTrigger value="email">Email Search</TabsTrigger>
          </TabsList>

          <TabsContent value="pipeline">
            <PipelineBoard />
          </TabsContent>

          <TabsContent value="vendors">
            <VendorTable />
          </TabsContent>

          <TabsContent value="email">
            <EmailSearch />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
