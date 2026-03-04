import processor

script = """#SC01
There once was a merchant who was incredibly rich. He could pave the whole street with gold coins. However, he was smart and saved his money.

#SC02
His son was different. He inherited the wealth and spent it foolishly. He made kites out of money and threw gold into the ocean just for fun.

#SC03
Soon, the son had nothing left but an old dressing gown and a pair of slippers. All his friends left him because he was poor.

#SC04
One kind friend sent him an old trunk with a message: "Pack up!" But the son had nothing to pack, so he sat inside the trunk himself.

#SC05
It was a magical trunk! When he pressed the lock, it flew out the chimney. He flew high above the clouds, hoping the bottom would not break.

#SC06
He landed safely in a forest in Turkey. He hid the trunk under dry leaves and walked into the town. Everyone there wore gowns and slippers, just like him.

#SC07
He saw a high castle with windows way up in the air. A nurse told him, "The Sultan’s daughter lives there. No one can visit her."

#SC08
That night, he flew in his trunk to the castle roof. He crept through the window and found the princess sleeping on a sofa.

#SC09
She woke up terrified. "Do not worry," he lied smoothly. "I am a Turkish Angel who came from the sky." The princess was delighted.

#SC10
He asked her to marry him. She said yes but gave him a condition. "You must come on Saturday for tea. My parents want a story that is both funny and moral."

#SC11
The merchant’s son bought a new gown and prepared a clever story. On Saturday, he flew back to the castle. The King and Queen were waiting.

#SC12
"Tell us a story," said the Queen. "It must be instructive." The King added, "And it must make us laugh." The son began his tale.

#SC13
"Once, there was a bundle of matches. They were very proud of their high birth from a great pine tree. They thought they were better than the iron pot."

#SC14
"The matches bragged about their past wealth. The other kitchen tools, like the bucket and the basket, were annoyed by their arrogance."

#SC15
"Suddenly, the maid came in and struck the matches. They flared up with a bright flame! They thought, 'Look how we shine!' But then, they burned out and became ash."

#SC16
The King and Queen loved the story about the vain matches. "You shall marry our daughter!" cried the King. The wedding was set for the next day.

#SC17
The son wanted to impress the people. He bought huge fireworks and rockets. That night, he flew into the sky and set them all off.

#SC18
Bang! Pop! The Turks jumped so high their slippers flew off. They cheered, "A real Turkish Angel has come down to us!"

#SC19
The son landed in the wood to hide his trunk. But a spark from the fireworks had fallen on it. The dry wood caught fire, and the trunk burned to ashes.

#SC20
He could no longer fly to his bride. He realized that his vanity and lies had cost him everything. The princess waited on the roof all day. Now, he wanders the world telling stories, forever regretting his foolish deception.
"""

parsed, _ = processor.parse_script(script)
chars = processor.extract_characters(parsed, script)

import pprint
print("Parsed Characters:")
pprint.pprint(chars.keys())

for item in parsed:
    if item['type'] == '대사':
         print(f"[{item['character']}] {item['text']}")
