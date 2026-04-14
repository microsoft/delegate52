from utils_context import calculate_context_stats, build_context_from_folder, expand_context
import os, sys, shutil, random, ujson as json
from .domain_base import DomainBase


class DomainPython(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_python.txt")
        self.sample_type = "python"
        self.summary = "Python code with functional test evaluation for correctness"
        self.description = "Python source code"
        self.file_format = [".py"]
        self.domain_parser = "custom"
        self.category = "code"
    
    def parse_context(self, context):
        import re as _re
        functions = []
        classes = []
        imports = []
        for filename, content in context.items():
            for m in _re.finditer(r'^\s*def\s+(\w+)', content, _re.MULTILINE):
                functions.append({"file": filename, "name": m.group(1)})
            for m in _re.finditer(r'^\s*class\s+(\w+)', content, _re.MULTILINE):
                classes.append({"file": filename, "name": m.group(1)})
            for m in _re.finditer(r'^((?:import|from)\s+.+)', content, _re.MULTILINE):
                imports.append({"file": filename, "statement": m.group(1).strip()})
        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
        }

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        return {
            "Functions": len(parsed["functions"]),
            "Classes": len(parsed["classes"]),
            "Imports": len(parsed["imports"]),
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        import importlib.util

        original_dir = os.getcwd()
        tmp_eval_folder = os.path.join(original_dir, f"tmp_eval_{random.randint(1000000, 9999999)}")

        with open(f"{self.samples_folder}{sample_id}/sample.json", "r") as f:
            sample = json.load(f)
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))

        target_state_id = target_state["state_id"]

        evaluation_result = calculate_context_stats(generated_context, reference_context)

        # copy over the content from the sample_id folder to the tmp_eval folder
        if os.path.exists(tmp_eval_folder):
            shutil.rmtree(tmp_eval_folder)

        shutil.copytree(f"{self.samples_folder}{sample_id}", tmp_eval_folder, dirs_exist_ok=True)

        # Strip scaffold files that the agent may have included but shouldn't overwrite
        scaffold_files = {"__init__.py", "testing.py"}
        generated_context = {k: v for k, v in generated_context.items() if k not in scaffold_files}

        # expand the generated context into the tmp_eval folder
        expand_context(generated_context, tmp_eval_folder, allow_overwrite=False)

        # Purge any cached modules that could conflict (basic_state, testing, etc.)
        stale_modules = [key for key in sys.modules if key == "testing" or key.startswith("basic_state")]
        for key in stale_modules:
            del sys.modules[key]

        try:
            # Load testing.py from the specific tmp_eval folder to avoid module caching issues
            testing_path = os.path.join(tmp_eval_folder, "testing.py")
            spec = importlib.util.spec_from_file_location("testing", testing_path)
            testing_module = importlib.util.module_from_spec(spec)
            
            # Add tmp_eval_folder to sys.path temporarily so testing.py can import its dependencies
            sys.path.insert(0, tmp_eval_folder)
            spec.loader.exec_module(testing_module)
            
            # Change to the tmp_eval directory to run tests with correct working directory
            os.chdir(tmp_eval_folder)
            evaluation_result.update(testing_module.run_tests(target_state_id))
        finally:
            os.chdir(original_dir)
            if tmp_eval_folder in sys.path:
                sys.path.remove(tmp_eval_folder)
            # Clean up modules imported from this tmp_eval folder to prevent cross-contamination
            stale_modules = [key for key in sys.modules 
                             if key == "testing" or key.startswith("basic_state")]
            for key in stale_modules:
                del sys.modules[key]
            # remove the temporary folder
            if os.path.exists(tmp_eval_folder):
                shutil.rmtree(tmp_eval_folder)

        return evaluation_result
