// Decompile specific addresses that the reference-driven export missed.
//
// The GUI logic of Datalyse is only referenced from Delphi's published-method
// tables (data), so ExportDecomp.java never selects it.  This script takes
// explicit addresses, defines a function there if Ghidra has not, decompiles
// it and writes one .c file per address.
//
//   args[0] = output directory
//   args[1] = comma-separated hex addresses (or a file with one per line)
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class DecompileAt extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File outDir = new File(args[0]);
        outDir.mkdirs();

        List<String> addrs = new ArrayList<>();
        File maybeFile = new File(args[1]);
        if (maybeFile.isFile()) {
            for (String line : java.nio.file.Files.readAllLines(maybeFile.toPath())) {
                line = line.trim();
                if (!line.isEmpty() && !line.startsWith("#")) addrs.add(line);
            }
        } else {
            for (String part : args[1].split(",")) {
                part = part.trim();
                if (!part.isEmpty()) addrs.add(part);
            }
        }
        println("addresses requested: " + addrs.size());

        DecompInterface ifc = new DecompInterface();
        ifc.toggleCCode(true);
        ifc.toggleSyntaxTree(true);
        ifc.setSimplificationStyle("decompile");
        if (!ifc.openProgram(currentProgram)) {
            println("decompiler failed to open program: " + ifc.getLastMessage());
            return;
        }

        ReferenceManager rm = currentProgram.getReferenceManager();
        int ok = 0, failed = 0;
        for (String s : addrs) {
            Address a = toAddr(s.trim());
            Function f = getFunctionAt(a);
            if (f == null) {
                disassemble(a);
                f = createFunction(a, null);
            }
            if (f == null) {
                println("NO FUNCTION at " + a);
                failed++;
                continue;
            }
            DecompileResults res = ifc.decompileFunction(f, 120, monitor);
            if (res == null || !res.decompileCompleted()) {
                println("DECOMPILE FAILED at " + a + " : " + ifc.getLastMessage());
                failed++;
                continue;
            }
            StringBuilder sb = new StringBuilder();
            sb.append("// ").append(f.getName()).append("  @ ").append(f.getEntryPoint())
              .append("  size ").append(f.getBody().getNumAddresses()).append('\n');
            sb.append(res.getDecompiledFunction().getC());
            sb.append("\n// --- called functions ---\n");
            for (Function callee : f.getCalledFunctions(monitor)) {
                sb.append("//   ").append(callee.getEntryPoint()).append(' ')
                  .append(callee.getName()).append('\n');
            }
            sb.append("\n// --- referenced strings ---\n").append(stringRefs(f, rm));
            String fn = String.format("%08X_%s.c", f.getEntryPoint().getOffset(),
                    f.getName().replaceAll("[^A-Za-z0-9_.]", "_"));
            try (PrintWriter pw = new PrintWriter(new File(outDir, fn))) {
                pw.print(sb.toString());
            }
            println("wrote " + fn);
            ok++;
        }
        println("done=" + ok + " failed=" + failed);
        ifc.dispose();
    }

    private String stringRefs(Function f, ReferenceManager rm) {
        StringBuilder sb = new StringBuilder();
        Set<String> seen = new HashSet<>();
        Memory mem = currentProgram.getMemory();
        ghidra.program.model.address.AddressIterator it = f.getBody().getAddresses(true);
        while (it.hasNext()) {
            Address a = it.next();
            for (Reference r : rm.getReferencesFrom(a)) {
                Address to = r.getToAddress();
                if (to == null || !to.isMemoryAddress()) continue;
                String s = null;
                try {
                    byte[] buf = new byte[80];
                    int n = mem.getBytes(to, buf);
                    if (n > 0) {
                        StringBuilder t = new StringBuilder();
                        for (int i = 0; i < n; i++) {
                            byte b = buf[i];
                            if (b == 0) break;
                            if (b < 0x20 || b > 0x7e) { t.setLength(0); break; }
                            t.append((char) b);
                        }
                        if (t.length() >= 2) s = t.toString();
                    }
                } catch (Exception ignored) { }
                if (s != null && seen.add(s)) {
                    sb.append("//   ").append(to).append("  \"").append(s).append("\"\n");
                }
            }
        }
        return sb.toString();
    }
}
