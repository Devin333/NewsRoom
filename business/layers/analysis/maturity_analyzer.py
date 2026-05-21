from __future__ import annotations

from business.layers.analysis import pipeline as rules


class MaturityAnalyzer:
    def analyze(self, signals, extraction_results, relations, context=None):
        maturities = []
        for result in extraction_results:
            for technology in result.technologies:
                paper_relations = [relation for relation in relations if relation.relation_type.value == "proposes" and relation.target_ref.object_id == technology.technology_id]
                project_relations = [relation for relation in relations if relation.relation_type.value == "implements" and relation.target_ref.object_id == technology.technology_id]
                community_relations = [relation for relation in relations if relation.relation_type.value == "discusses" and relation.target_ref.object_id == technology.technology_id]
                news_relations = [relation for relation in relations if relation.relation_type.value == "adopts" and relation.target_ref.object_id == technology.technology_id]
                score_value = rules._maturity_score(len(paper_relations), len(project_relations), len(community_relations), len(news_relations), technology)
                stage = rules._maturity_stage(score_value, len(paper_relations), len(project_relations), len(news_relations))
                maturities.append(
                    rules.Maturity(
                        technology_ref=rules.ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        stage=stage,
                        score=rules.Score(
                            value=score_value,
                            factors=[
                                rules._score_factor("paper_signal", min(1.0, len(paper_relations) / 3.0)),
                                rules._score_factor("project_implementation_signal", min(1.0, len(project_relations) / 3.0)),
                                rules._score_factor("community_usage_signal", min(1.0, len(community_relations) / 3.0)),
                                rules._score_factor("product_adoption_signal", min(1.0, len(news_relations) / 2.0)),
                                rules._score_factor("quality_signal", technology.confidence.value),
                            ],
                        ),
                        evidence_summary=f"{technology.name} has {len(paper_relations)} paper relation(s), {len(project_relations)} project relation(s).",
                        supporting_relations=[relation.relation_id for relation in paper_relations + project_relations + community_relations + news_relations],
                    )
                )
        return maturities
