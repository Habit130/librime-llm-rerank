// Model-free fixture driver. Commands/results never contain observation text.
#include <iostream>
#include <sstream>
#include <string>

#include "input_archive_producer.h"

int main(int argc, char** argv) {
  if (argc != 3)
    return 2;
  rime::InputArchiveProducer producer(argv[1], argv[2]);
  int64_t sequence = 0;
  std::string last_commit;
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream input(line);
    std::string command;
    input >> command;
    if (command == "poll") {
      producer.PollPolicyForTesting();
      std::cout << "effective=" << producer.locally_effective() << std::endl;
    } else if (command == "hold") {
      std::string fifo;
      input >> fifo;
      producer.HoldWorkerForTesting(fifo);
      std::cout << "held=1" << std::endl;
    } else if (command == "release") {
      producer.HoldWorkerForTesting("");
      std::cout << "release_requested=1" << std::endl;
    } else if (command == "admit" || command == "intent") {
      rime::InputArchiveObservation item;
      item.schema_id = "luna_pinyin";
      item.source_instance_id = argv[2];
      item.source_local_sequence = ++sequence;
      item.process_id = "invented-native-process";
      item.update_id = "native-update-" + std::to_string(sequence);
      item.continuity_segment_id = "invented-native-segment";
      item.plugin_stage = command == "admit" ? "commit" : "retraction";
      item.submission = "explicit";
      if (command == "admit") {
        item.payload_text = "虚构本地管理样例";
        item.retractable_commit = true;
        last_commit = item.update_id;
      } else {
        item.dependency_update_id = last_commit;
      }
      auto result = producer.TryAdmit(std::move(item));
      std::cout << "admitted=" << result.admitted
                << " durable=" << result.durable << std::endl;
    } else if (command == "flush") {
      std::cout << "flushed=" << producer.FlushForTesting(2000) << std::endl;
    } else if (command == "quit") {
      break;
    } else {
      std::cout << "invalid_command=1" << std::endl;
    }
  }
  return 0;
}
