import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Upload as UploadIcon, FileText } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { uploadContract, runAnalysis, uploadWarnings, type UploadResult } from "@/services/analysis";

export default function Upload() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const { toast } = useToast();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0];
      if (selectedFile.type === "application/pdf") {
        setFile(selectedFile);
      } else {
        toast({
          title: "Invalid file type",
          description: "Please upload a PDF file",
          variant: "destructive",
        });
      }
    }
  };

  const handleUpload = async () => {
    if (!file) return;

    setUploading(true);
    let uploaded: UploadResult;
    try {
      uploaded = await uploadContract(file);
    } catch (error) {
      toast({
        title: "Upload failed",
        description: error instanceof Error ? error.message : "Please try again",
        variant: "destructive",
      });
      setUploading(false);
      return;
    }

    // The contract is stored from here on; a failed analysis is reported
    // as that, not as a failed upload.
    const notes = uploadWarnings(uploaded);
    try {
      const result = await runAnalysis(uploaded.analysis_id);
      if (result.analysis_quality && result.analysis_quality.complete === false && result.analysis_quality.message) {
        notes.push(result.analysis_quality.message);
      }
      let description = `Analyzed ${result.total_clauses} clauses`;
      if (uploaded.ocr_info?.used) {
        const pages = uploaded.ocr_info.pages ?? 0;
        description += ` (OCR used on ${pages} page${pages === 1 ? "" : "s"})`;
      }
      toast({
        title: notes.length ? "Analysis complete, with warnings" : "Analysis complete",
        description: [description + ".", ...notes].join(" "),
        variant: notes.length ? "destructive" : "default",
      });
      setFile(null);
    } catch (error) {
      toast({
        title: "Uploaded, but the analysis failed",
        description:
          (error instanceof Error ? error.message : "The AI server didn't respond.") +
          " The contract is saved; open it from Analyses to run the analysis again.",
        variant: "destructive",
      });
      setFile(null);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Upload Contract</h1>
        <p className="text-muted-foreground">
          Upload a contract PDF for automated risk analysis
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Contract Document</CardTitle>
          <CardDescription>
            Upload a PDF file (max 20MB). The system will extract text and analyze it against your policy library.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-center w-full">
            <label
              htmlFor="dropzone-file"
              className="flex flex-col items-center justify-center w-full h-64 border-2 border-dashed rounded-lg cursor-pointer bg-muted/30 hover:bg-muted/50 transition-colors"
            >
              <div className="flex flex-col items-center justify-center pt-5 pb-6">
                <UploadIcon className="w-10 h-10 mb-3 text-muted-foreground" />
                <p className="mb-2 text-sm text-muted-foreground">
                  <span className="font-semibold">Click to upload</span> or drag and drop
                </p>
                <p className="text-xs text-muted-foreground">PDF files only (MAX. 20MB)</p>
              </div>
              <input
                id="dropzone-file"
                type="file"
                className="hidden"
                accept=".pdf"
                onChange={handleFileChange}
              />
            </label>
          </div>

          {file && (
            <div className="flex items-center gap-3 p-4 bg-muted rounded-lg">
              <FileText className="h-8 w-8 text-muted-foreground" />
              <div className="flex-1">
                <p className="font-medium">{file.name}</p>
                <p className="text-sm text-muted-foreground">
                  {(file.size / 1024 / 1024).toFixed(2)} MB
                </p>
              </div>
              <Button
                onClick={handleUpload}
                disabled={uploading}
              >
                {uploading ? "Analyzing..." : "Analyze Contract"}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>How it works</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>1. Upload your contract PDF file</p>
          <p>2. Our AI extracts and analyzes all clauses</p>
          <p>3. Each clause is compared against your policy library</p>
          <p>4. Risk scores are calculated based on policy violations</p>
          <p>5. Review detailed results with recommendations</p>
        </CardContent>
      </Card>
    </div>
  );
}
