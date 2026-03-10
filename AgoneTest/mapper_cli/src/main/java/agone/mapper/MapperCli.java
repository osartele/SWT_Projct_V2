package agone.mapper;

import com.sun.source.tree.AssignmentTree;
import com.sun.source.tree.ClassTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.ExpressionTree;
import com.sun.source.tree.IdentifierTree;
import com.sun.source.tree.ImportTree;
import com.sun.source.tree.MemberSelectTree;
import com.sun.source.tree.MethodInvocationTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.tree.NewClassTree;
import com.sun.source.tree.StatementTree;
import com.sun.source.tree.Tree;
import com.sun.source.tree.VariableTree;
import com.sun.source.util.JavacTask;
import com.sun.source.util.SourcePositions;
import com.sun.source.util.TreeScanner;
import com.sun.source.util.Trees;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import javax.lang.model.element.Modifier;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;

public final class MapperCli {
    private static final Set<String> ASSERTION_METHODS = new HashSet<>(Arrays.asList(
        "assertThat", "assertEquals", "assertTrue", "assertFalse", "assertNull", "assertNotNull",
        "assertSame", "assertNotSame", "assertArrayEquals", "fail", "isEqualTo", "contains",
        "containsExactly", "isTrue", "isFalse", "hasSize", "isEmpty"
    ));
    private static final Set<String> STOP_WORDS = new HashSet<>(Arrays.asList(
        "test", "should", "when", "then", "given", "returns", "return", "works", "work",
        "with", "without", "for", "and", "or", "uses", "use"
    ));

    private MapperCli() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 6) {
            System.err.println("usage: MapperCli <repoRoot> <moduleRoot> <testClassPath> <testMethodName> <topK> <scope>");
            System.exit(1);
        }
        Path repoRoot = Paths.get(args[0]).toAbsolutePath().normalize();
        Path moduleRoot = Paths.get(args[1]).toAbsolutePath().normalize();
        String testClassPath = args[2];
        String testMethodName = args[3];
        int topK = Integer.parseInt(args[4]);
        String scope = args[5];

        Map<String, Object> payload = run(repoRoot, moduleRoot, testClassPath, testMethodName, topK, scope);
        System.out.println(toJson(payload));
    }

    private static Map<String, Object> run(Path repoRoot, Path moduleRoot, String testClassPath, String testMethodName, int topK, String scope) throws Exception {
        Path testFile = repoRoot.resolve(testClassPath).normalize();
        TestContext context = analyzeTest(repoRoot, testFile, testMethodName);

        List<RepositoryMethod> methodIndex = collectMethods(moduleRoot, repoRoot);
        List<ScoredCandidate> astCandidates = scoreCandidates(methodIndex, context, testMethodName, topK);

        if ((astCandidates.isEmpty() || astCandidates.get(0).score <= 0.0) && "module_then_repo".equals(scope) && !repoRoot.equals(moduleRoot)) {
            methodIndex = deduplicateMethods(concat(methodIndex, collectMethods(repoRoot, repoRoot)));
            astCandidates = scoreCandidates(methodIndex, context, testMethodName, topK);
        }

        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("test_method_name", testMethodName);
        payload.put("analysis", context.toMap());
        List<Map<String, Object>> astPayload = new ArrayList<Map<String, Object>>();
        for (ScoredCandidate candidate : astCandidates) {
            astPayload.add(candidate.toMap());
        }
        payload.put("ast_candidates", astPayload);
        List<Map<String, Object>> methodPayload = new ArrayList<Map<String, Object>>();
        for (RepositoryMethod method : methodIndex) {
            methodPayload.add(method.toIndexMap());
        }
        payload.put("method_index", methodPayload);
        return payload;
    }

    private static List<RepositoryMethod> concat(List<RepositoryMethod> left, List<RepositoryMethod> right) {
        List<RepositoryMethod> combined = new ArrayList<>(left);
        combined.addAll(right);
        return combined;
    }

    private static List<RepositoryMethod> deduplicateMethods(List<RepositoryMethod> methods) {
        Map<String, RepositoryMethod> deduped = new LinkedHashMap<>();
        for (RepositoryMethod method : methods) {
            deduped.put(method.classPath + "#" + method.methodSignature, method);
        }
        return new ArrayList<>(deduped.values());
    }

    private static List<ScoredCandidate> scoreCandidates(List<RepositoryMethod> methods, TestContext context, String testMethodName, int topK) {
        List<ScoredCandidate> scored = new ArrayList<>();
        for (RepositoryMethod method : methods) {
            Map<String, Object> evidence = new LinkedHashMap<>();
            double score = 0.0;
            int directHits = context.directCalls.getOrDefault(method.methodName, 0);
            int assertionHits = context.assertionCalls.getOrDefault(method.methodName, 0);
            int receiverHits = context.receiverHits.getOrDefault(method.className + "#" + method.methodName, 0)
                + context.receiverHits.getOrDefault(orEmpty(method.classFqn) + "#" + method.methodName, 0);
            int staticImportHits = context.staticImportHits.getOrDefault(method.className + "#" + method.methodName, 0)
                + context.staticImportHits.getOrDefault(orEmpty(method.classFqn) + "#" + method.methodName, 0);
            int constructorHits = context.constructorHits.getOrDefault(method.className, 0)
                + context.constructorHits.getOrDefault(orEmpty(method.classFqn), 0);
            double packageBonus = method.packageName.equals(context.packageName) ? 0.5 : 0.0;
            double importBonus = context.importedClassNames.contains(method.className) ? 1.0 : 0.0;
            double namingOverlap = jaccard(camelTokens(testMethodName), camelTokens(method.methodName));
            double classNameOverlap = jaccard(camelTokens(testMethodName), camelTokens(method.className));

            score += receiverHits * 10.0;
            score += staticImportHits * 9.0;
            score += directHits * 3.0;
            score += assertionHits * 2.0;
            score += constructorHits > 0 ? 1.5 : 0.0;
            score += packageBonus + importBonus;
            score += namingOverlap + (classNameOverlap * 0.25);
            if (method.staticMethod && staticImportHits > 0) {
                score += 1.0;
            }

            evidence.put("receiver_hits", receiverHits);
            evidence.put("static_import_hits", staticImportHits);
            evidence.put("direct_hits", directHits);
            evidence.put("assertion_hits", assertionHits);
            evidence.put("constructor_hits", constructorHits);
            evidence.put("package_bonus", packageBonus);
            evidence.put("import_bonus", importBonus);
            evidence.put("naming_overlap", round(namingOverlap));
            evidence.put("class_name_overlap", round(classNameOverlap));

            scored.add(new ScoredCandidate(method, score, 0.0, evidence));
        }

        Collections.sort(scored, new Comparator<ScoredCandidate>() {
            @Override
            public int compare(ScoredCandidate left, ScoredCandidate right) {
                int scoreCompare = Double.compare(right.getScore(), left.getScore());
                if (scoreCompare != 0) {
                    return scoreCompare;
                }
                int classCompare = left.method.classPath.compareTo(right.method.classPath);
                if (classCompare != 0) {
                    return classCompare;
                }
                return left.method.methodSignature.compareTo(right.method.methodSignature);
            }
        });

        double topScore = scored.isEmpty() ? 0.0 : scored.get(0).score;
        List<ScoredCandidate> normalized = new ArrayList<>();
        for (ScoredCandidate candidate : scored) {
            double confidence = topScore <= 0.0 ? 0.0 : round(candidate.score / topScore);
            normalized.add(new ScoredCandidate(candidate.method, round(candidate.score), confidence, candidate.evidence));
        }
        return normalized.subList(0, Math.min(topK, normalized.size()));
    }

    private static TestContext analyzeTest(Path repoRoot, Path testFile, String testMethodName) throws Exception {
        ParsedUnit parsed = parseSingleFile(testFile);
        Map<String, String> importedClasses = new LinkedHashMap<>();
        Map<String, String> staticImports = new LinkedHashMap<>();
        for (ImportTree importTree : parsed.unit.getImports()) {
            String qualified = importTree.getQualifiedIdentifier().toString();
            if (importTree.isStatic()) {
                int separator = qualified.lastIndexOf('.');
                if (separator > 0) {
                    staticImports.put(qualified.substring(separator + 1), qualified.substring(0, separator));
                }
            } else {
                int separator = qualified.lastIndexOf('.');
                if (separator > 0) {
                    importedClasses.put(qualified.substring(separator + 1), qualified);
                }
            }
        }

        for (Tree typeDecl : parsed.unit.getTypeDecls()) {
            if (typeDecl instanceof ClassTree) {
                return analyzeTestClass(parsed, repoRoot, (ClassTree) typeDecl, importedClasses, staticImports, testMethodName);
            }
        }
        throw new IllegalStateException("No class found in test file: " + testFile);
    }

    private static TestContext analyzeTestClass(ParsedUnit parsed, Path repoRoot, ClassTree classTree, Map<String, String> importedClasses, Map<String, String> staticImports, String testMethodName) {
        Map<String, MethodTree> helperMethods = new LinkedHashMap<>();
        Map<String, String> fieldTypes = new LinkedHashMap<>();
        MethodTree targetMethod = null;

        for (Tree member : classTree.getMembers()) {
            if (member instanceof VariableTree) {
                VariableTree variable = (VariableTree) member;
                fieldTypes.put(variable.getName().toString(), simpleTypeName(variable.getType() == null ? "" : variable.getType().toString()));
            } else if (member instanceof MethodTree) {
                MethodTree method = (MethodTree) member;
                helperMethods.put(method.getName().toString(), method);
                if (method.getName().contentEquals(testMethodName)) {
                    targetMethod = method;
                }
            }
        }

        if (targetMethod == null) {
            throw new IllegalStateException("Unable to locate test method: " + testMethodName + " in " + repoRoot.relativize(parsed.path));
        }

        InvocationScanner scanner = new InvocationScanner(parsed, helperMethods, fieldTypes, importedClasses, staticImports, packageName(parsed.unit));
        scanner.scanMethod(targetMethod, false);
        return scanner.context;
    }

    private static List<RepositoryMethod> collectMethods(final Path searchRoot, Path repoRoot) throws Exception {
        final List<Path> javaFiles = new ArrayList<Path>();
        Files.walkFileTree(searchRoot, new SimpleFileVisitor<Path>() {
            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) throws IOException {
                if (attrs.isRegularFile() && file.toString().endsWith(".java") && isProductionSource(searchRoot, file)) {
                    javaFiles.add(file);
                }
                return FileVisitResult.CONTINUE;
            }
        });
        List<RepositoryMethod> methods = new ArrayList<RepositoryMethod>();
        for (Path javaFile : javaFiles) {
            ParsedUnit parsed = parseSingleFile(javaFile);
            String packageName = packageName(parsed.unit);
            for (Tree typeDecl : parsed.unit.getTypeDecls()) {
                if (typeDecl instanceof ClassTree) {
                    collectClassMethods(parsed, repoRoot, packageName, null, (ClassTree) typeDecl, methods);
                }
            }
        }
        return methods;
    }

    private static void collectClassMethods(ParsedUnit parsed, Path repoRoot, String packageName, String parentClass, ClassTree classTree, List<RepositoryMethod> methods) {
        String className = parentClass == null ? classTree.getSimpleName().toString() : parentClass + "." + classTree.getSimpleName();
        String classFqn = packageName.isEmpty() ? className : packageName + "." + className;
        String classPath = repoRoot.relativize(parsed.path).toString().replace('\\', '/');
        for (Tree member : classTree.getMembers()) {
            if (member instanceof MethodTree) {
                MethodTree method = (MethodTree) member;
                if (method.getReturnType() == null) {
                    continue;
                }
                methods.add(new RepositoryMethod(
                    packageName,
                    className,
                    classFqn,
                    classPath,
                    method.getName().toString(),
                    buildSignature(method),
                    method.getParameters().size(),
                    method.getModifiers().getFlags().contains(Modifier.STATIC)
                ));
            } else if (member instanceof ClassTree) {
                collectClassMethods(parsed, repoRoot, packageName, className, (ClassTree) member, methods);
            }
        }
    }

    private static ParsedUnit parseSingleFile(Path file) throws IOException {
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            throw new IllegalStateException("JDK compiler not available. Install a JDK and ensure javac is present.");
        }
        StandardJavaFileManager fileManager = compiler.getStandardFileManager(null, Locale.ROOT, StandardCharsets.UTF_8);
        Iterable<? extends JavaFileObject> units = fileManager.getJavaFileObjects(file.toFile());
        JavacTask task = (JavacTask) compiler.getTask(null, fileManager, null, Arrays.asList("-proc:none"), null, units);
        CompilationUnitTree unit = task.parse().iterator().next();
        Trees trees = Trees.instance(task);
        SourcePositions positions = trees.getSourcePositions();
        String source = new String(Files.readAllBytes(file), StandardCharsets.UTF_8);
        return new ParsedUnit(file, unit, source, positions);
    }

    private static String packageName(CompilationUnitTree unit) {
        return unit.getPackageName() == null ? "" : unit.getPackageName().toString();
    }

    private static boolean isProductionSource(Path root, Path file) {
        String relative = root.relativize(file).toString().replace('\\', '/').toLowerCase(Locale.ROOT);
        if (relative.contains("/src/test/") || relative.startsWith("src/test/") || relative.contains("/test/")) {
            return false;
        }
        String fileName = file.getFileName().toString().toLowerCase(Locale.ROOT);
        return !fileName.endsWith("test.java") && !fileName.endsWith("tests.java") && !fileName.endsWith("it.java");
    }

    private static String buildSignature(MethodTree method) {
        StringBuilder signature = new StringBuilder();
        signature.append(method.getReturnType().toString()).append(' ').append(method.getName()).append('(');
        for (int index = 0; index < method.getParameters().size(); index++) {
            VariableTree parameter = method.getParameters().get(index);
            if (index > 0) {
                signature.append(", ");
            }
            signature.append(parameter.getType().toString()).append(' ').append(parameter.getName());
        }
        signature.append(')');
        return signature.toString();
    }

    private static String orEmpty(String value) {
        return value == null ? "" : value;
    }

    private static double round(double value) {
        return Math.round(value * 10000.0) / 10000.0;
    }

    private static List<String> camelTokens(String value) {
        if (value == null || value.isEmpty()) {
            return Collections.emptyList();
        }
        String separated = value.replaceAll("([a-z0-9])([A-Z])", "$1 $2");
        List<String> tokens = new ArrayList<>();
        for (String token : separated.toLowerCase(Locale.ROOT).split("[^a-z0-9]+")) {
            if (!token.isEmpty() && !STOP_WORDS.contains(token)) {
                tokens.add(token);
            }
        }
        return tokens;
    }

    private static double jaccard(List<String> left, List<String> right) {
        if (left.isEmpty() && right.isEmpty()) {
            return 0.0;
        }
        Set<String> leftSet = new LinkedHashSet<>(left);
        Set<String> rightSet = new LinkedHashSet<>(right);
        if (leftSet.isEmpty() || rightSet.isEmpty()) {
            return 0.0;
        }
        Set<String> union = new LinkedHashSet<>(leftSet);
        union.addAll(rightSet);
        Set<String> intersection = new LinkedHashSet<>(leftSet);
        intersection.retainAll(rightSet);
        return intersection.size() / (double) union.size();
    }

    private static String simpleTypeName(String type) {
        if (type == null || type.isEmpty()) {
            return "";
        }
        String cleaned = type.replace("[]", "");
        int genericIndex = cleaned.indexOf('<');
        if (genericIndex >= 0) {
            cleaned = cleaned.substring(0, genericIndex);
        }
        int dotIndex = cleaned.lastIndexOf('.');
        return dotIndex >= 0 ? cleaned.substring(dotIndex + 1) : cleaned;
    }

    private static String invocationName(ExpressionTree select) {
        if (select instanceof MemberSelectTree) {
            return ((MemberSelectTree) select).getIdentifier().toString();
        }
        if (select instanceof IdentifierTree) {
            return ((IdentifierTree) select).getName().toString();
        }
        return select == null ? "" : select.toString();
    }

    private static boolean isAssertionMethod(String methodName) {
        return ASSERTION_METHODS.contains(methodName);
    }

    private static String receiverKey(String receiver, String methodName) {
        return receiver + "#" + methodName;
    }

    private static final class ParsedUnit {
        private final Path path;
        private final CompilationUnitTree unit;
        private final String source;
        private final SourcePositions positions;

        private ParsedUnit(Path path, CompilationUnitTree unit, String source, SourcePositions positions) {
            this.path = path;
            this.unit = unit;
            this.source = source;
            this.positions = positions;
        }
    }

    private static final class RepositoryMethod {
        private final String packageName;
        private final String className;
        private final String classFqn;
        private final String classPath;
        private final String methodName;
        private final String methodSignature;
        private final int parameterCount;
        private final boolean staticMethod;

        private RepositoryMethod(String packageName, String className, String classFqn, String classPath, String methodName, String methodSignature, int parameterCount, boolean staticMethod) {
            this.packageName = packageName;
            this.className = className;
            this.classFqn = classFqn;
            this.classPath = classPath;
            this.methodName = methodName;
            this.methodSignature = methodSignature;
            this.parameterCount = parameterCount;
            this.staticMethod = staticMethod;
        }

        private Map<String, Object> toIndexMap() {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("class_name", className);
            payload.put("class_fqn", classFqn);
            payload.put("class_path", classPath);
            payload.put("method_name", methodName);
            payload.put("method_signature", methodSignature);
            payload.put("parameter_count", parameterCount);
            payload.put("static_method", staticMethod);
            return payload;
        }
    }

    private static final class ScoredCandidate {
        private final RepositoryMethod method;
        private final double score;
        private final double confidence;
        private final Map<String, Object> evidence;

        private ScoredCandidate(RepositoryMethod method, double score, double confidence, Map<String, Object> evidence) {
            this.method = method;
            this.score = score;
            this.confidence = confidence;
            this.evidence = evidence;
        }

        private double getScore() {
            return score;
        }

        private Map<String, Object> toMap() {
            Map<String, Object> payload = method.toIndexMap();
            payload.put("score", score);
            payload.put("confidence", confidence);
            payload.put("evidence", evidence);
            return payload;
        }
    }

    private static final class TestContext {
        private final String packageName;
        private final Set<String> importedClassNames;
        private final Map<String, Integer> directCalls;
        private final Map<String, Integer> assertionCalls;
        private final Map<String, Integer> receiverHits;
        private final Map<String, Integer> staticImportHits;
        private final Map<String, Integer> constructorHits;
        private final List<String> helperExpansion;

        private TestContext(String packageName) {
            this.packageName = packageName;
            this.importedClassNames = new LinkedHashSet<>();
            this.directCalls = new LinkedHashMap<>();
            this.assertionCalls = new LinkedHashMap<>();
            this.receiverHits = new LinkedHashMap<>();
            this.staticImportHits = new LinkedHashMap<>();
            this.constructorHits = new LinkedHashMap<>();
            this.helperExpansion = new ArrayList<>();
        }

        private Map<String, Object> toMap() {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("package_name", packageName);
            payload.put("imported_class_names", new ArrayList<>(importedClassNames));
            payload.put("direct_calls", directCalls);
            payload.put("assertion_calls", assertionCalls);
            payload.put("receiver_hits", receiverHits);
            payload.put("static_import_hits", staticImportHits);
            payload.put("constructor_hits", constructorHits);
            payload.put("helper_expansion", helperExpansion);
            return payload;
        }
    }

    private static final class InvocationScanner extends TreeScanner<Void, ScanState> {
        private final ParsedUnit parsed;
        private final Map<String, MethodTree> helperMethods;
        private final Map<String, String> classFieldTypes;
        private final Map<String, String> importedClasses;
        private final Map<String, String> staticImports;
        private final Set<String> visitedHelpers;
        private final TestContext context;

        private InvocationScanner(ParsedUnit parsed, Map<String, MethodTree> helperMethods, Map<String, String> classFieldTypes, Map<String, String> importedClasses, Map<String, String> staticImports, String packageName) {
            this.parsed = parsed;
            this.helperMethods = helperMethods;
            this.classFieldTypes = classFieldTypes;
            this.importedClasses = importedClasses;
            this.staticImports = staticImports;
            this.visitedHelpers = new LinkedHashSet<>();
            this.context = new TestContext(packageName);
            this.context.importedClassNames.addAll(importedClasses.keySet());
        }

        private void scanMethod(MethodTree method, boolean helper) {
            ScanState state = new ScanState(classFieldTypes, false);
            for (VariableTree parameter : method.getParameters()) {
                state.localTypes.put(parameter.getName().toString(), simpleTypeName(parameter.getType().toString()));
            }
            if (helper) {
                context.helperExpansion.add(method.getName().toString());
            }
            scan(method.getBody(), state);
        }

        @Override
        public Void visitVariable(VariableTree node, ScanState state) {
            if (node.getType() != null) {
                state.localTypes.put(node.getName().toString(), simpleTypeName(node.getType().toString()));
            }
            if (node.getInitializer() instanceof NewClassTree) {
                NewClassTree created = (NewClassTree) node.getInitializer();
                increment(context.constructorHits, simpleTypeName(created.getIdentifier().toString()));
            }
            return super.visitVariable(node, state);
        }

        @Override
        public Void visitAssignment(AssignmentTree node, ScanState state) {
            if (node.getVariable() instanceof IdentifierTree && node.getExpression() instanceof NewClassTree) {
                IdentifierTree identifier = (IdentifierTree) node.getVariable();
                NewClassTree created = (NewClassTree) node.getExpression();
                state.localTypes.put(identifier.getName().toString(), simpleTypeName(created.getIdentifier().toString()));
                increment(context.constructorHits, simpleTypeName(created.getIdentifier().toString()));
            }
            return super.visitAssignment(node, state);
        }

        @Override
        public Void visitMethodInvocation(MethodInvocationTree node, ScanState state) {
            String methodName = invocationName(node.getMethodSelect());
            boolean assertionScope = state.insideAssertion || isAssertionMethod(methodName);
            increment(context.directCalls, methodName);
            if (assertionScope) {
                increment(context.assertionCalls, methodName);
            }
            resolveReceiver(node.getMethodSelect(), methodName, state);
            resolveStaticImport(methodName);
            expandHelper(methodName);

            ScanState nested = state.child(assertionScope);
            ExpressionTree select = node.getMethodSelect();
            if (select instanceof MemberSelectTree) {
                scan(((MemberSelectTree) select).getExpression(), nested);
            }
            for (ExpressionTree argument : node.getArguments()) {
                scan(argument, nested);
            }
            return null;
        }

        @Override
        public Void visitNewClass(NewClassTree node, ScanState state) {
            increment(context.constructorHits, simpleTypeName(node.getIdentifier().toString()));
            return super.visitNewClass(node, state);
        }

        private void resolveReceiver(ExpressionTree select, String methodName, ScanState state) {
            if (!(select instanceof MemberSelectTree)) {
                return;
            }
            MemberSelectTree member = (MemberSelectTree) select;
            String expression = member.getExpression().toString();
            String inferredType = state.localTypes.get(expression);
            if (inferredType == null && expression.startsWith("this.")) {
                inferredType = state.localTypes.get(expression.substring(5));
            }
            if (inferredType == null) {
                inferredType = importedClasses.containsKey(expression) ? expression : simpleTypeName(expression);
            }
            if (inferredType != null && !inferredType.isEmpty()) {
                increment(context.receiverHits, receiverKey(inferredType, methodName));
                String importedFqn = importedClasses.get(inferredType);
                if (importedFqn != null) {
                    increment(context.receiverHits, receiverKey(importedFqn, methodName));
                }
            }
        }

        private void resolveStaticImport(String methodName) {
            if (!staticImports.containsKey(methodName) && !staticImports.containsKey("*")) {
                return;
            }
            String owner = staticImports.containsKey(methodName) ? staticImports.get(methodName) : staticImports.get("*");
            increment(context.staticImportHits, receiverKey(simpleTypeName(owner), methodName));
            increment(context.staticImportHits, receiverKey(owner, methodName));
        }

        private void expandHelper(String methodName) {
            MethodTree helper = helperMethods.get(methodName);
            if (helper == null || visitedHelpers.contains(methodName)) {
                return;
            }
            visitedHelpers.add(methodName);
            scanMethod(helper, true);
        }
    }

    private static final class ScanState {
        private final Map<String, String> localTypes;
        private final boolean insideAssertion;

        private ScanState(Map<String, String> seed, boolean insideAssertion) {
            this.localTypes = new LinkedHashMap<>(seed);
            this.insideAssertion = insideAssertion;
        }

        private ScanState child(boolean assertionState) {
            return new ScanState(localTypes, assertionState);
        }
    }

    private static void increment(Map<String, Integer> counts, String key) {
        if (key == null || key.isEmpty()) {
            return;
        }
        counts.put(key, counts.getOrDefault(key, 0) + 1);
    }

    private static String toJson(Object value) {
        StringBuilder builder = new StringBuilder();
        appendJson(builder, value);
        return builder.toString();
    }

    @SuppressWarnings("unchecked")
    private static void appendJson(StringBuilder builder, Object value) {
        if (value == null) {
            builder.append("null");
            return;
        }
        if (value instanceof String) {
            builder.append('"').append(escape((String) value)).append('"');
            return;
        }
        if (value instanceof Number || value instanceof Boolean) {
            builder.append(value);
            return;
        }
        if (value instanceof Map) {
            builder.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> entry : ((Map<String, Object>) value).entrySet()) {
                if (!first) {
                    builder.append(',');
                }
                first = false;
                builder.append('"').append(escape(entry.getKey())).append('"').append(':');
                appendJson(builder, entry.getValue());
            }
            builder.append('}');
            return;
        }
        if (value instanceof List) {
            builder.append('[');
            boolean first = true;
            for (Object item : (List<Object>) value) {
                if (!first) {
                    builder.append(',');
                }
                first = false;
                appendJson(builder, item);
            }
            builder.append(']');
            return;
        }
        builder.append('"').append(escape(String.valueOf(value))).append('"');
    }

    private static String escape(String value) {
        return value
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t");
    }
}



