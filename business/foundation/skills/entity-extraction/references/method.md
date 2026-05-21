# Method

## Decision Criteria

An extracted entity must be named or strongly abbreviated in the item and must carry a direct evidence span.

## Step-by-Step Procedure

Inspect title, summary, and content; group aliases; choose a schema type; normalize to the most specific stable name; and set confidence based on span clarity.

## Scoring or Classification Rules

Use `company` for organizations building products, `model` for named AI models, `repo` for repository slugs, `framework` for reusable software frameworks, and `metric` for benchmark or performance names.

## Edge Cases

When a product and model share a name, choose the type supported by the surrounding words. When a repository slug contains an organization prefix, extract the repo and organization separately only if both matter to the item.
