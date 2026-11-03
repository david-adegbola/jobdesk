import unittest

import skills


def job(title, ad_text="", personal=False, category="Forestry", job_id=1):
    return {"id": job_id, "title": title, "ad_text": ad_text, "url": "", "personal": personal,
            "category": category}


CV = {"id": 7, "title": "Forestry CV", "language": "en",
      "content": {"skills": "GIS: QGIS and map reading\nWant to learn: drones",
                  "experience": "2025: Field assistant", "full_name": "Alex"}}


class SkillsTests(unittest.TestCase):
    def test_finnish_and_english_ads_count_towards_the_same_skill(self):
        jobs = [job("Metsäasiantuntija", "Paikkatieto ja QGIS. Puukauppa metsänomistajien kanssa.", job_id=1),
                job("Forest Specialist", "GIS, timber trade and forest owners. Python is a plus.", job_id=2),
                job("Forestry Professional, Intern", "Wood procurement with forest owners.", job_id=3)]
        result = skills.analyse(jobs, [CV])
        role = result["role_types"][0]
        self.assertEqual((role["id"], role["jobs"], role["internships"]), ("forest_specialist", 3, 1))
        study = {s["id"]: s["jobs"] for s in role["study"]}
        self.assertEqual(study, {"forest_owners": 3, "timber_trade": 3})   # python: only one ad
        self.assertIn("gis", {s["id"] for s in role["have"]})
        self.assertEqual(role["closest_cv"], {"id": 7, "title": "Forestry CV"})

    def test_want_to_learn_row_is_not_counted_as_a_skill_held(self):
        jobs = [job("Paikkatietoasiantuntija", "Drooni-kuvaus ja QGIS", job_id=1),
                job("GIS Specialist", "Drone mapping", job_id=2)]
        role = skills.analyse(jobs, [CV])["role_types"][0]
        self.assertEqual([s["id"] for s in role["study"]], ["drones"])
        self.assertEqual([s["id"] for s in role["have"]], ["gis", "qgis"])

    def test_draft_replaces_the_want_to_learn_row_and_keeps_the_rest(self):
        role = {"id": "gis_data", "label": "GIS & forest data", "label_fi": "Paikkatieto ja metsätieto",
                "closest_cv": {"id": 7, "title": "Forestry CV"}}
        study = [{"label": "Remote sensing / laser scanning", "label_fi": "Kaukokartoitus ja laserkeilaus"},
                 {"label": "Python", "label_fi": "Python"}]
        draft = skills.draft_cv(role, [CV], study)
        self.assertEqual(draft["title"], "GIS & forest data CV")
        self.assertEqual(draft["content"]["target_role"], "GIS & forest data")
        self.assertEqual(draft["content"]["skills"],
                         "GIS: QGIS and map reading\nWant to learn: Remote sensing / laser scanning, Python")
        self.assertEqual(draft["content"]["experience"], "2025: Field assistant")
        self.assertEqual(draft["based_on"], "Forestry CV")
        finnish = skills.draft_cv(role, [CV], study, language="fi")
        self.assertTrue(finnish["content"]["skills"].endswith("Haluan oppia: Kaukokartoitus ja laserkeilaus, Python"))

    def test_personal_jobs_keep_their_category_and_sort_last(self):
        jobs = [job("Asentaja", "Hitsaus ja trukkikortti", personal=True, category="Industrial", job_id=1),
                job("Asentaja", "Hitsaus", personal=True, category="Industrial", job_id=2),
                job("Metsuri", "Moottorisaha", job_id=3)]
        result = skills.analyse(jobs, [])
        self.assertEqual([r["id"] for r in result["role_types"]], ["field_work", "personal-industrial"])
        self.assertEqual(result["role_types"][1]["study"][0]["id"], "welding")
        self.assertIsNone(result["role_types"][0]["closest_cv"])
        self.assertEqual(skills.draft_cv(result["role_types"][0], [], [])["content"],
                         {"target_role": "Forest & field work"})
