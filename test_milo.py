import processor

code = """#SC01
"Perhaps the colors I seek aren't things I can borrow. Maybe they have been inside me all along, waiting for me to notice them." """

parsed, _ = processor.parse_script(code)
import pprint
pprint.pprint(parsed)
