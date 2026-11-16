"""Compare executable source while allowing transport documentation removal."""
import ast


def executable_tree(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if isinstance(body, list):
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                body.pop(0)
            body[:] = [statement for statement in body if not isinstance(statement, ast.Pass)]
    return ast.dump(tree, include_attributes=False)
