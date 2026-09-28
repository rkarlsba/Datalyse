// Export decompiled C from the Datalyse.exe Ghidra project.
//
//   args[0] = output directory
//   args[1] = optional text file of hex addresses of interest (one per line).
//             When given, only functions that reference one of those addresses
//             (or that contain one) are decompiled -- which is how the app's
//             own logic is separated from the statically linked VCL.
//   args[2] = optional "all" to force a full decompile.
//
// Writes functions.txt (inventory) plus one .c file per decompiled function.
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.TreeMap;

public class ExportDecomp extends GhidraScript {

    private static final int MAX_C_LINES = 3000;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File outDir = new File(args[0]);
        outDir.mkdirs();
        boolean all = args.length > 2 && args[2].equalsIgnoreCase("all");

        Set<Long> interesting = new HashSet<>();
        if (args.length > 1 && !args[1].isEmpty() && new File(args[1]).isFile()) {
            for (String line : java.nio.file.Files.readAllLines(new File(args[1]).toPath())) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                try {
                    interesting.add(Long.parseUnsignedLong(line.replace("0x", ""), 16));
                } catch (NumberFormatException ignored) { }
            }
        }
        println("addresses of interest: " + interesting.size() + "  all=" + all);

        // ---- inventory ----------------------------------------------------
        TreeMap<Long, Function> byAddr = new TreeMap<>();
        FunctionIterator fit = currentProgram.getFunctionManager().getFunctions(true);
        while (fit.hasNext()) {
            Function f = fit.next();
            byAddr.put(f.getEntryPoint().getOffset(), f);
        }
        try (PrintWriter pw = new PrintWriter(new File(outDir, "functions.txt"))) {
            pw.println("# address size name  [references-interesting]");
            for (Function f : byAddr.values()) {
                pw.printf("%08X %6d %s\n", f.getEntryPoint().getOffset(),
                        f.getBody().getNumAddresses(), f.getName());
            }
        }
        println("functions: " + byAddr.size());

        // ---- which functions reference the interesting addresses? ---------
        ReferenceManager rm = currentProgram.getReferenceManager();
        Set<Long> selected = new HashSet<>();
        if (!interesting.isEmpty()) {
            for (Long target : interesting) {
                Address a = currentProgram.getAddressFactory().getDefaultAddressSpace()
                        .getAddress(target);
                for (Reference r : rm.getReferencesTo(a)) {
                    Function f = getFunctionContaining(r.getFromAddress());
                    if (f != null) selected.add(f.getEntryPoint().getOffset());
                }
            }
            for (Long target : interesting) {
                Function f = getFunctionContaining(currentProgram.getAddressFactory()
                        .getDefaultAddressSpace().getAddress(target));
                if (f != null) selected.add(f.getEntryPoint().getOffset());
            }
        }
        println("functions referencing interesting addresses: " + selected.size());

        // ---- decompile ----------------------------------------------------
        DecompInterface ifc = new DecompInterface();
        ifc.toggleCCode(true);
        ifc.toggleSyntaxTree(true);
        ifc.setSimplificationStyle("decompile");
        if (!ifc.openProgram(currentProgram)) {
            println("decompiler failed to open program: " + ifc.getLastMessage());
            return;
        }

        File decDir = new File(outDir, "decomp");
        decDir.mkdirs();
        int done = 0, skipped = 0, failed = 0;
        List<Function> targets = new ArrayList<>();
        for (Function f : byAddr.values()) {
            if (f.isThunk() || f.getBody().getNumAddresses() <= 3) { skipped++; continue; }
            if (all || selected.contains(f.getEntryPoint().getOffset())) targets.add(f);
        }
        println("targets: " + targets.size());

        for (Function f : targets) {
            if (monitor.isCancelled()) break;
            try {
                DecompileResults res = ifc.decompileFunction(f, 60, monitor);
                if (res == null || !res.decompileCompleted()) {
                    failed++;
                    continue;
                }
                String c = res.getDecompiledFunction().getC();
                if (c == null) { failed++; continue; }
                String[] lines = c.split("\n");
                StringBuilder sb = new StringBuilder();
                if (lines.length > MAX_C_LINES) {
                    sb.append("// TRUNCATED: ").append(lines.length).append(" lines total\n");
                    for (int i = 0; i < MAX_C_LINES; i++) sb.append(lines[i]).append('\n');
                } else {
                    sb.append(c);
                }
                sb.append("\n// --- called functions ---\n");
                for (Function callee : f.getCalledFunctions(monitor)) {
                    sb.append("//   ").append(callee.getEntryPoint()).append(' ')
                      .append(callee.getName()).append('\n');
                }
                sb.append("\n// --- referenced strings ---\n");
                sb.append(stringRefs(f, rm));
                String fn = String.format("%08X_%s.c", f.getEntryPoint().getOffset(),
                        f.getName().replaceAll("[^A-Za-z0-9_.]", "_"));
                try (PrintWriter pw = new PrintWriter(new File(decDir, fn))) {
                    pw.print(sb);
                }
                done++;
            } catch (Exception e) {
                failed++;
            }
        }
        println("decompiled=" + done + " failed=" + failed + " skipped=" + skipped);
        ifc.dispose();
    }

    private String stringRefs(Function f, ReferenceManager rm) {
        StringBuilder sb = new StringBuilder();
        Set<String> seen = new HashSet<>();
        ghidra.program.model.address.AddressIterator it =
                f.getBody().getAddresses(true);
        while (it.hasNext()) {
            Address a = it.next();
            for (Reference r : rm.getReferencesFrom(a)) {
                Address to = r.getToAddress();
                if (to == null || !to.isMemoryAddress()) continue;
                String s = null;
                try {
                    ghidra.program.model.mem.Memory mem = currentProgram.getMemory();
                    byte[] buf = new byte[64];
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
