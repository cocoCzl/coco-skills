import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;
import com.sun.source.tree.ClassTree;
import com.sun.source.tree.AnnotationTree;
import com.sun.source.tree.MethodInvocationTree;
import com.sun.source.tree.LiteralTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.tree.VariableTree;
import com.sun.source.util.JavacTask;
import com.sun.source.util.SourcePositions;
import com.sun.source.util.Trees;
import com.sun.source.util.TreeScanner;

/**
 * Dependency-free JDK parser used only for source facts. It parses files without
 * compiling, loading project classes, resolving dependencies, or executing target code.
 */
public final class SourceFactExtractor {
    private static String quote(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") + "\"";
    }

    public static void main(String[] args) throws IOException {
        if (args.length == 0) {
            System.err.println("usage: SourceFactExtractor <file.java>...");
            System.exit(2);
        }
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            System.err.println("A full JDK is required");
            System.exit(3);
        }
        // Keep this helper compatible with JDK 8.  It is deliberately
        // dependency-free and only parses source files; it never compiles the
        // analyzed project.
        List<String> paths = new ArrayList<>(Arrays.asList(args));
        paths.sort(Comparator.naturalOrder());
        try (StandardJavaFileManager files = compiler.getStandardFileManager(null, null, null)) {
            Iterable<? extends JavaFileObject> units = files.getJavaFileObjectsFromStrings(paths);
            JavacTask task = (JavacTask) compiler.getTask(null, files, null, Arrays.asList("-proc:none"), null, units);
            Iterable<? extends CompilationUnitTree> parsed = task.parse();
            Trees trees = Trees.instance(task);
            SourcePositions positions = trees.getSourcePositions();
            for (CompilationUnitTree unit : parsed) {
                String source = unit.getSourceFile().toUri().getPath();
                new TreeScanner<Void, Void>() {
                    private long line(com.sun.source.tree.Tree tree) {
                        long offset = positions.getStartPosition(unit, tree);
                        return offset < 0 || unit.getLineMap() == null ? 1 : unit.getLineMap().getLineNumber(offset);
                    }
                    public Void visitClass(ClassTree tree, Void unused) {
                        System.out.println("{\"kind\":\"class\",\"file\":" + quote(source) + ",\"line\":" + line(tree) + ",\"name\":" + quote(tree.getSimpleName().toString()) + "}");
                        return super.visitClass(tree, unused);
                    }
                    public Void visitVariable(VariableTree tree, Void unused) {
                        System.out.println("{\"kind\":\"variable\",\"file\":" + quote(source) + ",\"line\":" + line(tree) + ",\"name\":" + quote(tree.getName().toString()) + ",\"type\":" + quote(tree.getType() == null ? "" : tree.getType().toString()) + "}");
                        return super.visitVariable(tree, unused);
                    }
                    public Void visitMethod(MethodTree tree, Void unused) {
                        System.out.println("{\"kind\":\"method\",\"file\":" + quote(source) + ",\"line\":" + line(tree) + ",\"name\":" + quote(tree.getName().toString()) + "}");
                        return super.visitMethod(tree, unused);
                    }
                    public Void visitAnnotation(AnnotationTree tree, Void unused) {
                        System.out.println("{\"kind\":\"annotation\",\"file\":" + quote(source) + ",\"line\":" + line(tree) + ",\"name\":" + quote(tree.getAnnotationType().toString()) + "}");
                        return super.visitAnnotation(tree, unused);
                    }
                    public Void visitMethodInvocation(MethodInvocationTree tree, Void unused) {
                        System.out.println("{\"kind\":\"call\",\"file\":" + quote(source) + ",\"line\":" + line(tree) + ",\"method\":" + quote(tree.getMethodSelect().toString()) + "}");
                        return super.visitMethodInvocation(tree, unused);
                    }
                    public Void visitLiteral(LiteralTree tree, Void unused) {
                        Object value = tree.getValue();
                        if (value instanceof String) {
                            System.out.println("{\"kind\":\"string\",\"file\":" + quote(source) + ",\"line\":" + line(tree) + ",\"value\":" + quote((String) value) + "}");
                        }
                        return super.visitLiteral(tree, unused);
                    }
                }.scan(unit, null);
            }
        }
    }
}
